---
name: new-plugin
description: Build a new TAP plugin FROM ITS SPEC — standalone repository, package-mode dist `<slug>-tap`, manifest, models, edges, GRIFT, in-package ci record and tests, CI wiring. Refuses to start without a spec; runs create-plugin-spec first when none exists.
disable-model-invocation: true
allowed-tools: Read Write Edit Bash(git *) Bash(gh *) Bash(mkdir *) Bash(mv *) Bash(cp *) Bash(ls *) Glob Grep Skill AskUserQuestion
argument-hint: <slug> [<path-to-spec>]
---

# Build a New TAP Plugin

> **Skill source-of-truth.** Canonical location: `tap_plugins/skills/new-plugin/SKILL.md`; `.claude/skills/new-plugin`
> is a wiring symlink (`scripts/wire-skills.sh`). Edit the canonical. Sibling skills: `create-plugin-spec`
> (the spec, always first), `add-model`, `add-edge`, `add-page`, `add-panel`.

A TAP plugin is an **installable Python package in its own repository**: a wheel-buildable dist with a
`tap.plugins` entry point, installed by a boot record from a git source or an index. There is no monorepo
phase and no in-tree `plugins/` directory: every plugin is standalone from its first commit, owned by
whoever runs it — this organisation, a customer, an outsider — and TAP never assumes which. This skill is
independent of any one GitHub organisation; where it needs a location it asks.

## Gate 0: There is a spec, or you stop

The spec drives everything below. Resolve it before touching a file:

1. `$ARGUMENTS` names a spec path → use it.
2. Otherwise look for `specs/spec-<slug>-v0.md` in the plugin repository (or the checkout the author points
   you at). Exactly one → use it.
3. Otherwise a pre-authored planning doc may exist (`docs/misc/preplugin-<slug>-v?.md` in a TAP checkout, or
   a path the author gives). Review and graduate it (below), then continue.
4. **Otherwise invoke [`create-plugin-spec`](../create-plugin-spec/SKILL.md) and stop this skill.** That
   skill runs the author interview, the prior-art search and the requirement buy-in, and lands
   `specs/spec-<slug>-v0.md`. Re-run `new-plugin` when it exists. Scaffolding without a reviewed spec is the
   shape that never converges; this gate is how a spec is forced.

Confirm in one sentence which branch you took before proceeding.

### Graduating a pre-authored planning doc (path 3 only)

Treat the doc as the author's intent, not a draft to replace. Run the checklist, report every finding in
one summary, ask at most one bounded batch of questions (≤ 4, `AskUserQuestion`), normalise, get one
explicit approval, then graduate it. Graduation crosses two repositories and is **two landings, never one
`mv`**: (a) `cp` the normalised doc to `specs/spec-<slug>-v0.md` in the plugin repository and land it there
by PR; (b) delete the planning doc from the TAP checkout in its own docs-tier PR (`No-issue:` or
`Part-of:` the plugin's epic) — never leave that checkout dirty, and never let the deletion ride an
unrelated core PR. No redirect stub at the old path; history is in git.

| # | Check | Fail looks like |
| :---: | --- | --- |
| a | Required sections (`create-plugin-spec` Step 2): Plugin Identity (four rows), Philosophy, Goals table, Requirements table, per-requirement sections with two-line metadata and ACID tables | Ad-hoc metadata block; missing Goals; a `Status:` at document level |
| b | RIDs `req-<slug>-<noun>`, unique, kebab-case; ACIDs `req-<slug>-<noun>-<n>` | Duplicates, missing prefix |
| c | Statuses ∈ Proposed · Approved for Development · In Development · Implemented · Verified · Backlog | `Draft`, `Pre-Plugin Planning` |
| d | Identity table holds only slug, display name, description, kind | Dist, entry point, repo, dev workspace restated |
| e | Planning artifacts removed: `Strategic Check`, `Initial Implementation Outline`, `Open Questions` tail (fold each into its requirement's Notes) | Any of them present |
| f | Concrete requirements, testable ACs, no "we'll figure it out" in normative text | Hand-waving |

## Step 1: Where does the plugin live? (ask; never assume)

Before creating anything, ask the author in one batch:

- **Host and owner**: which GitHub organisation or user (or other forge) owns the repository. Never default
  to the organisation that develops TAP core.
- **Repository name**: convention is the dist name, `<slug-dashed>-tap` (`git-serious-tap`, `aws-core-tap`).
  The repo name is not identity (`req-tap-plugin-arch-identity-4`), so an owner may choose otherwise; record
  the choice.
- **Visibility**: public or private.
- **Does it already exist?** If yes, work in it; if no, creating it is an outward-facing action — show the
  exact plan (owner, name, visibility, default branch, first-wave files) and create it only on an explicit yes.
- **Which CI the owner runs.** TAP offers a reusable per-repo plugin CI the owner may call (Step 10); any
  other CI, code review or scanning is the owner's own plumbing and this skill does not assume it. **If the
  owner is `unified-systems-com`, invoke [`unified-systems-plugin-conventions`](../unified-systems-plugin-conventions/SKILL.md)
  during the bootstrap wave** — that skill holds this organisation's plumbing (review shims, plugin-ci
  caller, scanner configs, DCO, release) so it never leaks into the owner-neutral steps here. Another
  organisation supplies its own equivalent.
- **Does this plugin need to run in a FIPS-mode TAP deployment?** Most authors will say no, and that is
  fine: the manifest still declares a `[fips]` posture (the contract is declare-vs-decide, and absent is
  undeclared, not compatible), but you declare what the validator observes and skip the analysis. See the
  opt-out path in Step 6.
- **Where the development workspace is.** Plugins are developed against a TAP session: `spawn-session.sh
  <label> --from <record> --dev-plugins <slug>` clones the plugin repository into `_dev-plugins/<slug>/` in
  the worktree and flips its install source to editable. Confirm the author has, or wants, such a session.

The org ruleset (where one exists) applies the moment a repository is created — the default branch is
PR-only and force-push is refused — so the first commit to `main` is the bootstrap (`README.md`, `LICENSE`,
`.gitignore`) and everything else arrives by PR.

## Step 2: The identity chain — derive, never author

All four must agree; the pre-boot conformance gate fails closed otherwise (`req-tap-plugin-arch-identity`):

| Item | Value | Note |
| --- | --- | --- |
| Slug | `<slug>` (snake_case) | The one identity: manifest `slug` == entry-point key == namespace segment |
| Dist | **`<slug-dashed>-tap`** (PEP 503) | The pre-2026-08-26 `tap-plugin-<slug>` prefix is legacy: gates accept it with a warning, never emit it. `tap/plugin_identity.py:dist_name_for_slug` is the derivation |
| Import namespace | `tap_plugin.<slug>` | PEP 420: **no** `tap_plugin/__init__.py`, so dists share the namespace |
| Entry point | `<slug> = "tap_plugin.<slug>.apps:<Slug>Config"` | Under `[project.entry-points."tap.plugins"]` |

## Step 3: Repository layout (the standalone shape)

The repository root holds packaging and test collection; the **runtime package** is `tap_plugin/<slug>/` and
is the only thing that ships in the wheel. Tests, boot records and GRIFT live **inside** the package so they
ride the wheel and run against any install (`pytest --pyargs tap_plugin.<slug>`). Reference: any current
plugin repository (zizmor-tap is the cleanest leaf).

```text
<repo>/
  pyproject.toml            # dist, entry point, hatch-vcs (template below)
  __init__.py               # pytest collection MARKER for this project dir (comment only; ships in no wheel)
  README.md  LICENSE  .gitignore
  specs/spec-<slug>-v0.md   # the spec (NOT in the wheel)
  .github/workflows/        # Step 10 — the owner's CI and review callers
  tap_plugin/               # PEP 420 namespace — NO __init__.py here
    <slug>/                 # the runtime package
      __init__.py           # docstring only
      apps.py               # one TapPluginConfig subclass; registrations in ready()
      tap-plugin.toml       # the manifest
      py.typed
      boot/ci.boot.json     # the in-package `ci` record (req-boot-bootstrap-ci-record)
      models/  edges/  grift/  migrations/  static/<slug>/  templates/<slug>/  panels/  collectors/  domain/
      tests/                # the plugin's own tests, IN the wheel
```

`.gitignore` minimum: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `dist/`,
`*.egg-info/`.

**`pyproject.toml` template** (hatchling + hatch-vcs; the version is VCS-derived, never hand-set):

```toml
# Identity chain (pre-boot conformance gate enforces agreement):
#   slug = "<slug>"  ·  distribution = "<slug-dashed>-tap"  ·  import namespace = "tap_plugin.<slug>"
#   entry-point key = "<slug>"
[project]
name = "<slug-dashed>-tap"
description = "TAP <Display Name> plugin — <one line>."
requires-python = ">=3.14"
dynamic = ["version"]
dependencies = []                    # Tier-0 RUNTIME deps (Step 6); other plugins by their dist name

[project.entry-points."tap.plugins"]
<slug> = "tap_plugin.<slug>.apps:<Slug>Config"

# The plugin's OWN dev closure (PEP 735), so its suite runs in a bare checkout. Never installed by boot.
[dependency-groups]
dev = ["pytest>=8.3", "pytest-django>=4.9", "factory-boy>=3.3"]

[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.version]
source = "vcs"

[tool.hatch.version.raw-options]
fallback_version = "0.0.0"

[tool.hatch.build.targets.wheel]
only-include = ["tap_plugin/<slug>"]
```

Never add `root = "../.."` (a retired monorepo artifact) and never author a version.

## Step 4: Core files

- `tap_plugin/<slug>/apps.py` — one `TapPluginConfig` subclass. No `name`/`label`/`verbose_name`: `name` is
  derived from the module path, `label`/`verbose_name` from the manifest. Collector and panel-type
  registrations go in `ready()`, imported inside it.
- `tap_plugin/<slug>/tap-plugin.toml` — per `spec-tap-plugin-manifest-v0.md`: `manifest_version`,
  `plugin_version`, `requires_tap` (the core floor the plugin is tested against), `slug`, `name`,
  `description`, `depends_on` (Step 6), `[fips]`, `[models]`, `[edges]`, `[grift]`, `[[boot.records]]`.
  Class paths use `tap_plugin.<slug>.…`. **`[fips]` is required** (`spec-fips.md`): a pure-Python plugin with
  no crypto deps declares `status = "compatible"`; a non-validated provider declares
  `status = "uses-nonvalidated"` with a `reason`. Absent is undeclared, not compatible. Authors who opted out
  of FIPS in Step 1 declare whatever `validate_plugin`'s `crypto-providers` check reports and move on.
- `tap_plugin/<slug>/boot/ci.boot.json` — the `ci` record (Step 8).
- `tap_plugin/<slug>/migrations/__init__.py` — empty; `tap_plugin/<slug>/tests/__init__.py` — empty.
- Root `__init__.py` — the pytest collection marker, comment only (copy a sibling's).
- Root `README.md` — what this plugin owns, what lives elsewhere, what to read first, how to stand it up.
  Keep it true as the plugin grows; a stale README is spec drift.

Every requirement in the spec that lands flips to `Implemented` in the same change.

## Step 5: Models, edges, pages, panels

- Models: the [`add-model`](../../../tap_grid/skills/add-model/SKILL.md) skill, one per model; re-export via
  `tap_plugin.<slug>.models`. Every TAP-managed type declares `DEFAULT_DIMENSIONS` per the spec's default
  dimensions table (a dimension-less type is a design error to justify in the spec).
- Edges: the [`add-edge`](../../../tap_grid/skills/add-edge/SKILL.md) skill; slugs `<ACTION>_<OBJECT>__<slug>`
  (the edge-naming guard rejects bare verbs).
- Pages and panel types: every one already has a requirement in the spec (`req-<slug>-page-*`,
  `req-<slug>-panel-*`); [`add-page`](../../../tap_web/skills/add-page/SKILL.md) / [`add-panel`](../../../tap_web/skills/add-panel/SKILL.md)
  fill it, they do not create it. Templates changing Tailwind classes need `/tailwind-rebuild`.
- Icons: `spec-grid-icon.md`; every `ENTITY_ICON` has an SVG at `static/<slug>/icons/<key>.svg`.

## Step 6: Dependencies and configuration (hard rules)

- **No plugin config in core infrastructure** (`req-tap-plugin-arch-runtime-4`): not in compose, not in
  core settings. Plugins self-configure through plugin-owned mechanisms (secrets under `TAP_SECRETS_ROOT`).
- **No new third-party dependency without the author's explicit approval.**
- **FIPS — two paths, chosen in Step 1.** *Opted out (most authors):* run `validate_plugin --strict`, declare
  in `[fips]` exactly what its `crypto-providers` check reports (`compatible` when it finds nothing;
  `uses-nonvalidated` naming the providers with reason "not targeting FIPS deployments" when it does), and
  add the `fips_waivers` entry the check derives for your own `ci` record so that stack boots. Nothing else;
  a FIPS-mode operator who later wants your plugin does the waiving on their side. *Targeting FIPS
  deployments:* check every dependency before adding it (`spec-fips.md`) — bundled-OpenSSL wheels and
  non-OpenSSL crypto (`ring`/`aws-lc-rs`, `libsodium`, Go binaries, JVMs) run silently non-FIPS; prefer the
  system-OpenSSL build or a validated equivalent, and declare honestly when unavoidable.
- **Three tiers** (`req-tap-plugin-arch-dependencies`): Tier 0 package deps in `pyproject` `dependencies`
  (other plugins by dist name, e.g. `"github-core-tap"`; a dependency still published under a legacy
  `tap-plugin-<slug>` name is referenced by that name until it renames). Tier 1 load order in the manifest
  `depends_on` — if you `from tap_plugin.<other> import …`, declare it with a `note`; the pre-boot gate fails
  closed on an undeclared import. Tier 2 data order (you read nodes another collector produced) is
  profile-explicit, never a `depends_on`.

## Step 7: GRIFT seed data

Per `spec-grift-v0.md`; validate against `tap_grid/schemas/grift-document.schema.json`. Entity ids from
`scripts/uuid7`, minted once. Revising content: **version bump** (new `batch_entity.entity_id`, bumped name;
node/edge ids stable) is the shipping path; `import_plugin_grift <slug> --force-batches=<id>` is DEBUG-only
dev iteration. Editing a bundle in place without either is silently ignored.

## Step 8: The `ci` boot record (in-package, required)

`tap_plugin/<slug>/boot/ci.boot.json`, named `ci` (`req-boot-bootstrap-ci-record`): the stack the plugin's
own tests run in and the one claim per-plugin CI may make — that the plugin is correct against the
dependencies it DECLARES and nothing else. Its `install` is exactly the `depends_on` closure (pinned to
released tags of each dependency, with a `note` saying so) plus the plugin itself pinned at a commit (the
consumer flips self to editable). `population` seeds the plugin's own GRIFT and only the dependency bundles
its pages mount. Deliberately excluded: every other plugin, all credentials, anything that reaches the
network. Declare it under `[[boot.records]]` in the manifest with its `sha256`; `validate_plugin --strict`
checks that the record installs the whole closure, optional dependencies included.

## Step 9: Tests (in the package)

`tap_plugin/<slug>/tests/test_<slug>_manifest.py` runs `validate_plugin` at structure and strict levels
against `Path(__file__).resolve().parents[1]` (the package dir — resolves the same from a checkout and an
installed wheel). Add behaviour tests named for what they test (`test_<slug>_edges.py`, `test_<slug>_pack.py`),
building collectors via `__new__` where a credential would otherwise be needed. Do not re-implement what the
validation system already checks.

## Step 10: CI wiring (owner-specific; first PR wave)

TAP assumes nothing about the owner's CI, code review or scanners; wire whatever the owner runs (Step 1).
The one piece TAP itself offers is its **reusable per-repo plugin CI** (`req-tap-plugin-extdev-repo-ci`): a
thin `.github/workflows/ci.yml` that calls `<tap-core-owner>/tap/.github/workflows/plugin-ci.yml@<sha>` with
`plugin_slug` and a read-only PAT the owner provides for fetching the core harness. Two independent pins:
the workflow SHA picks the validation logic; the manifest's `requires_tap` picks the core it runs against.
It boots the plugin's in-package `ci` record and runs its tests — the same gates as Step 11, on every PR.
Optional; an owner with their own CI runs the same commands there.

## Step 11: Validate, in layers

1. Structure, no Django: `python -m tap_plugins.validate_plugin tap_plugin/<slug> --strict` (inside the
   session's `web` container — never host Python).
2. Boot the `ci` record with the checkout editable: `spawn-session.sh <label> --from
   'git+<repo-url>@<rev>#ci' --dev-plugins <slug>` — this exercises the conformance gate, the reconciliation
   guard, the dependency gate and the crypto-BOM gate.
3. `manage.py plugins` in that stack: identity, surfaces, load health, both dependency directions.
4. `pytest --pyargs tap_plugin.<slug>` in that stack.

Fix every gate failure before opening the PR; they fail closed by design.

## Step 12: Land and release

Every change rides a PR to the plugin repository's default branch; the org ruleset (where one exists)
refuses direct pushes. Commit trailers name the issue (`Closes:` / `Part-of:`). Releases are immutable
`v<x.y.z>` tags cut by `scripts/release-plugin.sh` from a `--dev-plugins` workspace (pre-release guard:
`validate_plugin --strict` + the plugin's tests; PR-based landing; tag). A release changes no boot pin —
consumers bump their own records deliberately.

## Step 13: Spec back in sync

Flip every implemented requirement to `Implemented`; head the design-time Model catalog / Edge types
sections "Superseded by the manifest as of v<x>" and keep only rows that record a decision
(`create-plugin-spec` Step 2). Spec drift is a bug.
