---
title: Plugin Dependency Scoping — Developer Mode & Install-Footprint Slimming (Backlog)
date: 2026-07-02
status: design-note
audience:
  - llm
  - developer
related_docs:
  - docs/misc/doc-plugin-source-identity-deps-handoff.md
  - docs/misc/doc-plugin-boot-install-handoff.md
  - docs/misc/doc-plugin-deps-reporting-thoughts.md
related_specs:
  - tap_plugins/specs/spec-tap-plugin-architecture.md
  - tap_plugins/specs/spec-tap-plugin-testing.md
  - specs/spec-tap-boot-v0.md
---

# Plugin Dependency Scoping — Developer Mode & Install-Footprint Slimming

Two backlog concerns on the same axis: **what a plugin's dependency closure includes,
and when.** Developer mode adds deps for the *develop/test* path; install-footprint
slimming removes deps a given *deployment* doesn't use. Both are captured here as
deliberate targets, not oversights; neither is critical path (2026-07-02: everything runs
in developer mode for the foreseeable future, and the plugin system already delivers the
coarse slim-down — see Part B/Layer C). Spec anchors: `req-tap-plugin-arch-dev-deps` (Part A),
`req-tap-plugin-arch-slim-install` (Part B).

---

## Part A — Developer mode (per-plugin dev dependency groups)

### The current reality (the implicit thing to formalize)

Every migrated plugin's `pyproject.toml` declares `dependencies = []` (Tier-0 runtime) and
**no dev dependencies at all**. Plugin tests run only because they execute inside the
**shared root venv**, which carries the root's `[dependency-groups]` `dev` group (`pytest`,
`pytest-django`, `pytest-xdist`, `factory-boy`, `mypy`, `ruff`, …). So today a plugin
**free-rides** on the root's dev group; it has no independent developer-mode story.

This is fine while plugins live in the monorepo. It **breaks at eviction**: a plugin split
into its own repo, `uv sync`'d standalone, gets its runtime deps and *nothing else* — no
test framework, no factories — so its own suite cannot run. Developer mode is the missing
piece that makes an evicted plugin independently developable and testable. It is the
dev-dependency sibling of the airgapped `wheelhouse` source (`req-tap-plugin-arch-sources-6`):
both are things a self-contained plugin needs that the monorepo currently hides.

### The mechanism (uv supports this natively)

- **PEP 735 dependency groups** — `[dependency-groups]` in the plugin's `pyproject.toml`,
  the same standard the root already uses. A `dev` group holds test/lint tooling; pulled
  with `uv sync --group dev` (or `uv run --group dev pytest`). **Dev-group deps never ship
  in the wheel** — they are local-development metadata, not package metadata. This is the
  right tool for developer mode.
- **Not** `[project.optional-dependencies]` (extras): extras *do* ship in wheel metadata and
  exist for opt-in *runtime* features a consumer installs (`pip install pkg[feature]`) — a
  different purpose (Part B / Layer A). Do not put dev tooling in extras.

### The boundary that must hold

Developer mode is a **local-checkout workflow** (`uv sync --group dev` in a plugin's repo),
**never a boot/install-section concept.** Dev deps must not flow into a deployed instance
through the boot `install` path — the same discipline as "the profile carries no secrets."
The `install` section installs the wheel/editable runtime; dev groups are a developer's
local choice. Nobody should ever wire a `dev: true` into a boot profile.

### Sequencing

- **Cheap edge, safe pre-demand:** teach the `new-plugin` scaffold (the skill) to give every
  new plugin a `[dependency-groups]` `dev` group seeded with the baseline test tooling, so
  the free-riding habit does not calcify and new plugins are born standalone-testable.
- **Lands with eviction / two-tier testing:** actually running each plugin's suite against
  *its own* dev group (`uv run --group dev pytest` in the plugin dir), instead of the shared
  root venv, is the "two-tier plugin testing" build. Pair it with the first real eviction,
  same as the `wheelhouse` pilot. Consumes into `spec-tap-plugin-testing.md`.

**Demand trigger:** the first plugin eviction to a standalone repo, or any need to run a
plugin's suite outside the shared root venv.

---

## Part B — Install-footprint slimming (extras & the three-layer model)

The appeal: a deployed instance should not ship packages (or system binaries) it does not
use. This spans **three layers, three different tools** — the common mistake is assuming
Python extras reach all three. They do not.

### Layer A — Python packages → extras / dependency-groups

`[project.optional-dependencies]` (extras) gate *PyPI* deps: `pip install tap[saml]` pulls
extra Python packages only when the feature is wanted; they ship in wheel metadata so a
consumer opts in.

- **Real win — providers with heavy deps.** `django-allauth[saml]` pulls `python3-saml`,
  which itself needs `xmlsec`/`libxml2` (system libs) — gating SAML behind an extra saves a
  Python dep *and* avoids dragging in system libraries. LDAP is similar.
- **Caveat on the motivating examples.** Google and generic-OIDC providers ship *inside*
  core `django-allauth` (pure Python, no extra package). Extras cannot slim them out; you can
  only *not activate* them via config (`INSTALLED_APPS` / `SOCIALACCOUNT_PROVIDERS`). So for
  those two specifically the slimming is **config-level, not package-level**. The extras
  pattern applies to providers/features that pull their *own* PyPI deps, not to allauth's
  built-in providers.

### Layer B — System binaries → Docker image variants / build args

`git`, `postgresql-client`, `curl` come from `apt-get` in the `Dockerfile`. **Python extras
cannot touch the OS layer.** Slimming git out is an *image-build* switch — a build arg
(`--build-arg INSTALL_GIT=0`) or a separate image variant / multi-stage build, not an extra.

- The git binary exists only for the `git` **source strategy** (uv shells out to it for VCS
  installs; added to the Dockerfile 2026-07-01, commit `e45095c5`). A deployment that never
  uses git sources does not need it.
- **The layers correlate — the payoff.** A fully airgapped **`wheelhouse`-only** deployment
  (`req-tap-plugin-arch-sources-6`) needs **no git binary, no network, no index credential** — so
  the slimmest possible image drops out of the source-type choice: wheelhouse strategy →
  image variant without git/curl → ship only the plugins that deployment installs plus their
  exact wheel closure. Source-type and image-slimming are one decision seen twice.

### Layer C — TAP plugins → already delivered (coarse-grained)

The boot `install` section + per-plugin Tier-0 deps already means an instance **does not ship
`boto3` unless it installs `aws_core`**, nor `PyYAML` unless `github_core`, nor `sigstore`
unless `sigstore_core`. The plugin system *is* feature-scoped dependency slimming at plugin
granularity, and the `wheelhouse` carries exactly that closure and nothing more. Extras
(Layer A) would add *sub*-plugin granularity — a single plugin with an optional backend.

### The cross-cutting discipline (cheap edge to keep now)

Whichever layer gates a feature, the rule is **fail loud at boot if config activates
something whose dependency or binary is absent** — a SAML provider enabled but `[saml]` not
installed; a `git` source named in a profile on a no-git image. That should be a boot-time
coherence failure, not an `ImportError` at first request — exactly the NetBox failure-mode
that TAP's existing static coherence guards already prevent for plugin slugs
(`req-boot-install-section-3`). Cheap foundational edge; the expensive parts (splitting
images, carving extras) wait for a deployment that actually needs the smaller footprint.

**Demand trigger:** a deployment (early adopter / customer) whose footprint, attack surface,
or airgap constraints make the full image genuinely too big — not before.
