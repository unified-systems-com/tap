---
title: Plugin Source-Identity, Versioning & Dependencies — Design Handoff
date: 2026-07-01
status: handoff
audience:
  - llm
  - developer
related_docs:
  - docs/misc/doc-plugin-boot-install-handoff.md
  - docs/misc/doc-plugin-system-refactor-framing.md
related_specs:
  - tap_plugins/specs/spec-tap-plugin-architecture.md
  - specs/spec-tap-boot-v0.md
---

# Plugin Source-Identity, Versioning & Dependencies — Design Handoff

> **Status: design locked; identity + versioning + Tier-0 dependencies IMPLEMENTED across the
> full samsite plugin set (updated 2026-07-01).** This captures a design session that ran *after*
> the install MVP landed (see `doc-plugin-boot-install-handoff.md`). Every decision below is
> prior-art-grounded and written into `spec-tap-plugin-architecture.md` as `req-tap-plugin-arch-identity`
> (now `Implemented`) / `-sources` (`Proposed` — all plugins use `editable` local sources during the
> monorepo transition) / `-versioning` (`Implemented`, hatch-vcs) / `-dependencies` (`Partially
> Implemented` — Tier-0 built; `depends_on` schema + resolver deferred, `samsite` being the first real
> cross-plugin case). All 9 samsite-set plugins now ship the namespace `tap_plugin.<slug>` layout,
> `tap-plugin-<slug>` dists, hatch-vcs versions, and Tier-0 deps declared in-plugin, verified at boot
> by the pre-boot conformance gate. This note remains the orientation + rationale + the record of what
> is still deferred (sources registry, index integrity/signing, dependency resolver).

## What this covers

Four intertwined questions the install MVP surfaced but deferred: **how do we name and
identify a plugin, where does it come from, how is it versioned/pinned, and how do plugins
depend on each other** — given the plugins are on private GitHub repos and there will be a
mix of standalone repos and monorepo-batched plugins from day one.

Each decision was checked against prior art via a focused search (the systems are named per
decision below). The recurring discipline: **lean on uv/the ecosystem for the hard parts,
declare the TAP-specific parts now, defer the machinery that only pays off at scale.**

## The locked decisions (with the one-line why)

### Identity (`req-tap-plugin-arch-identity`)
- **Slug = the one true identity** (entry-point key == manifest slug == namespace segment).
  TAP enforces uniqueness in its own boot/registry — it owns the private index, so no PyPI
  PEP 541 dispute machinery needed.
- **Dist = `tap-plugin-<slug>`**; the private index gives ownership (Terraform-provider shape).
- **Import namespace = `tap_plugin.<slug>`** (PEP 420 native namespace, singular to avoid the
  `tap_plugins` app). **Lead with it from the first migration** — cheap now, expensive to
  retrofit across N repos. (This supersedes the MVP's top-level `<slug>` import; `genericom`
  gets re-pointed — see Follow-ons.)
- **Repo is decoupled/free** — mirror the slug (standalone) or a subdir (monorepo). Repo-path-
  as-identity (Go/Actions) rejected: worst fit for the standalone+monorepo mix.
- **Owners set the namespace; TAP enforces it** via a pre-boot **conformance gate** (dist ==
  entry-key == namespace == manifest slug, else fail closed). The plugin-creation skill emits
  conformant packages; the gate is the backstop for hand-authored/third-party plugins.

### Sources (`req-tap-plugin-arch-sources`)
- **Source-type strategy registry** — each `type` is a strategy answering (install spec,
  `is_satisfied`, credential scope). Adding a source is adding a strategy, not editing pre-boot.
  Prior art: Nix fetchers, Terraform source addressing.
- **`git` = bootstrap/dev (now)**: `tap-plugin-<slug> @ git+<url>@<ref>` (+ `#subdirectory=<slug>`
  for monorepos). Private auth via a **git credential helper** (`url.insteadOf`/`GIT_ASKPASS`)
  fed from `TAP_SECRETS_ROOT` — **never a token in the URL** (leaks into `direct_url.json`).
- **`index` = durable target**: a private **object bucket + `dumb-pypi`** (real PEP 503 static
  index), install by version, one credential via `~/.netrc`. **GitHub Releases was verified and
  rejected** as a backend (private assets aren't `--find-links`-consumable — browser URL
  dead-ends under auth, only the REST asset-ID endpoint works; GitHub Packages has no Python
  index at all).
- **`wheelhouse` = offline/airgapped (added 2026-07-02)**: a **mounted directory of pre-built
  wheels**, installed with `uv pip install --no-index --find-links <dir> tap-plugin-<slug>==<ver>`.
  The **filesystem twin of `index`** — same install-by-version model, wheels arrive on a volume
  instead of over HTTP, so **no network and no credential**. Must also carry the plugins' Tier-0
  PyPI deps as wheels (`--no-index` fails loud on a missing one). Wheels are CI-built where the git
  tag lives (tagless ⇒ `0.0.0` fallback); the volume is the trust boundary. Motivated by monorepo
  eviction: once a plugin loses its `editable` source, this is the install path for a deployment
  that grants no git/repo/network access. **Not critical path** — design locked, build demand-gated
  on eviction + a healthy leaf plugin. Pilot (held): `fedramp_20x_ksi`.
- **`grid` = future**: pull a plugin from another running TAP instance — a drop-in strategy.
- **The profile carries NO secrets on any path** (`wheelhouse`/`grid` reach for no credential at all).

### Versioning (`req-tap-plugin-arch-versioning`)
- **VCS-derived PEP 440 versions via `hatch-vcs`** (`{tag}.dev{n}+g{sha}`) — George's "Go
  property" (context self-contained in the identifier) realized the Pythonic way, no
  hand-maintained version file. The embedded commit hash means a version can't name two
  different sources.
- **Integrity is layered + sidecar-free**: version pins the *source*; the index's per-file
  `sha256` (verified by uv/pip) pins the *bytes*. No hand-maintained lockfile.
- **Append-only index** (CI policy / bucket-versioning) makes "the version is the pin" true on a
  self-hosted index; a changed `sha256` is the tamper tell.
- **Signing is the deferred edge** (hostile-index defense); reproducible builds are the bonus
  that would make the commit-in-version transitively byte-pinning.

### Dependencies (`req-tap-plugin-arch-dependencies`)
- **Tier 0 — package deps → `pyproject.toml`** (incl. plugin→plugin, version specifiers not
  git-URLs). uv resolves the closure + diamonds, fail-closed. Free.
- **Tier 1 — load/registration order → manifest `depends_on`** (slug edges, min-version,
  optional). Django migration `dependencies` is the in-stack model; Debian `Depends` the vocab.
- **Tier 2 — seed order → mostly rides on `depends_on`**; the runtime-data dependency
  (collector-produced nodes) stays **explicit in the profile** (auditability).
- **Declare all three now; defer the topological-sort resolver** until hand-ordering bites (≈
  Django's `topological_sort.py`, cycle-detecting, fail-closed). A cheap **boot consistency
  gate** (min-versions + profile-order-consistent-with-`depends_on`) lands now.
- **One runtime = one version, fail-closed** (uv/Jenkins). No OSGi-style multi-version, no
  second resolver.

## Build sequencing (when picked up)

This is design-ahead-of-need; most of it rides *into* the plugin-set migration rather than
being a separate build. Order:

1. **Fold into the migration recipe** (the immediate follow-on from the install MVP): as each
   plugin migrates to package-mode, author it with the namespace `tap_plugin.<slug>`, VCS
   version (`[tool.hatch.version] source = "vcs"`), Tier-0 pyproject deps, and Tier-1/2
   `depends_on`. These are declarations, near-free at authoring time.
2. **Pre-boot conformance gate** — extend `tap/preboot.py`'s identity check to assert
   dist/entry-key/namespace/slug agreement. Small, high-value, do it with the first namespaced
   plugin.
3. **Boot consistency gate** — validate min-versions + profile-order-vs-`depends_on`. Small.
4. **`git` credential-helper wiring** — resolve the token from `TAP_SECRETS_ROOT`, inject via
   `url.insteadOf`/`GIT_ASKPASS` for the install subprocess. Needed the first time a real
   private plugin installs from git. (Verify uv's exact private-git credential handling +
   whether it tokenizes `direct_url.json` before wiring — a named pre-build check.)
5. **Deferred, build when it bites**: the `index` source (bucket + `dumb-pypi`), the
   topological-sort resolver, the `grid` source, artifact signing, the registry/report surface.

## Dependencies on other threads / follow-ons

- **`genericom` re-point**: the MVP migrated it as top-level `genericom`; under the namespace
  decision it becomes `tap_plugin.genericom`. Mechanical, folds into the first namespaced pass.
- **`gryphon_playground` migration waits** on the in-flight gryphon-engine refactor (another
  session), same as it was deferred during the slug-rename.
- **hatchling namespace-package build** (`tap_plugin/<slug>` without a namespace `__init__.py`)
  is a small build-config detail to spike alongside the first real migration.
- **Plugin-creation skill bump** — emit namespace + VCS-version + `depends_on`-ready plugins so
  first-party authors never hand-set them.

## Validation posture

Same as the install MVP: `scripts/dc exec -T web uv run pytest …` (multi-session — always
`scripts/dc`; host Python is stale). The conformance + consistency gates want unit tests
alongside the existing `tap/tests/test_preboot.py`. Promotion is gated on the dev-validation
suite (`spec-dev-validation.md`).
