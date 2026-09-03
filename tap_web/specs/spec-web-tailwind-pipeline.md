# Web Tailwind Build Pipeline Specification

## Philosophy

TAP's web layer uses Tailwind CSS for layout, typography, and color, served from `tap_web/static/tap_web/css/tailwind.css`. Tailwind's JIT compiler generates only the utility class rules it observes in scanned source files. Any class string that appears in a template but isn't present at compile time becomes a no-op in the browser: the HTML attribute is set, but there is no matching CSS rule, so the layout silently fails to apply.

The compiled stylesheet is **checked into git** and **regenerated on demand by a skill** rather than a container watcher. The skill orchestrates a checksum-verified install of the standalone tailwindcss binary into a Docker named volume and then runs the build — entirely inside the web container, never touching the host filesystem. A pinned auto-memory triggers the AI workflow to invoke the skill when a template edit changes which utility class strings are present.

## Architecture (v1)

The pipeline has three parts. The image stays slim — no tailwindcss binary baked in — and the entrypoint stays simple.

1. **The `/tailwind-rebuild` skill** — `tap_web/skills/tailwind-rebuild/SKILL.md`. Invoked by the AI workflow on relevant template edits (driven by the auto-memory at `feedback_tailwind_class_edit_invoke_rebuild_skill.md`). Orchestrates `docker/install-tailwindcss.sh` followed by `docker/tailwind-build`, both inside the running web container via `scripts/dc exec web …`. Idempotent: cached-binary path runs ~50ms verify + ~500ms rebuild.
2. **The on-demand binary install** — `docker/install-tailwindcss.sh`. Downloads the pinned standalone binary from GitHub Releases, verifies SHA-256 against `tap_web/third_party_manifest.toml` (implements `req-grid-thirdparty-manifest.sec-9/-10`), and installs to `/opt/tailwind/tailwindcss`. The install path is backed by the `tailwind_bin` named Docker volume (declared in `docker-compose.yml`), so the first invocation downloads and subsequent invocations reuse. The binary lives only in Docker's internal volume storage — `dc down -v` wipes it; nothing executes on the host filesystem.
3. **The build wrapper** — `docker/tailwind-build`. Thin shell wrapper that runs `/opt/tailwind/tailwindcss` against `tailwind.config.js`, producing the minified `tap_web/static/tap_web/css/tailwind.css`. Content paths come from the config: `tap_web/templates`, `tap_viz/templates`, `plugins/**/templates`.

The compiled stylesheet is committed in git. Production deployments serve the committed artifact unchanged — no build step at deploy time. Dev edits go through the skill, and the skill commits the regenerated artifact alongside the template change.

### Why this shape (and why not a container watcher)

An earlier iteration of this spec built an always-on container watcher: Dockerfile install of the binary, entrypoint one-shot + bash-poll watcher, gitignored output. That worked but was a stack of hoops to get a build-time tool onto disk in a container that didn't otherwise need it — Dockerfile install RUN, image-time pre-build RUN, entrypoint stages, DEBUG gating, poll-loop workaround for the v3.4.17 binary's broken `--watch` and Docker Desktop's missing inotify forwarding. Tearing that out in favor of the skill+memory pattern keeps the image slim and the runtime simple at the cost of: an unwatched human edit (no AI in the loop, no manual skill invocation) reintroduces the original "did I forget to rebuild?" failure mode.

The trade-off was accepted because this project's editing workflow is AI-driven and the memory reliably triggers the skill. A human-only editing workflow would want the watcher back.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | No Silent Failures | A new utility class in a template should never silently lack its CSS rule. |
| 2. | Dev-Loop Speed | The rebuild should happen automatically during template iteration, not on demand. |
| 3. | Scoped Surface | The build should scan every template directory that ships utility classes — `tap_web/templates`, `tap_viz/templates`, and any plugin templates under `plugins/*/templates`. |
| 4. | Reproducible | The build should produce identical output on any contributor's machine, in CI, and in the dev Docker stack. |
| 5. | No Hidden Dependencies | Whatever build mechanism is chosen should declare its tool versions explicitly so the artifact is deterministic. |
| 6. | Spawn-Session Friendly | New session worktrees should pick up the pipeline automatically without manual setup. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-tailwind-pipeline-rebuild | [On-Demand Rebuild](#on-demand-rebuild) | Implemented | `/tailwind-rebuild` skill + auto-memory; v1 replaced the v0 always-on watcher |
| req-web-tailwind-pipeline-content-paths | [Content Path Coverage](#content-path-coverage) | Implemented | `plugins/**/templates/**/*.html` in `tailwind.config.js` content |
| req-web-tailwind-pipeline-determinism | [Deterministic Output](#deterministic-output) | Implemented | Version pinned in `tap_web/third_party_manifest.toml`; install script enforces SHA-256 |
| req-web-tailwind-pipeline-spawn-integration | [Spawn-Session Integration](#spawn-session-integration) | Implemented | Skill + manifest + named volume travel with the worktree; first invocation per session installs |
| req-web-tailwind-pipeline-manual-fallback | [Documented Manual Path](#documented-manual-path) | Implemented | `docs/misc/doc-dev-tailwind-rebuild.md` covers manual rebuild for the rare skill-failure case |

## Requirements

### On-Demand Rebuild
----
RID: `req-web-tailwind-pipeline-rebuild`

Status: `Implemented`

The compiled `tap_web/static/tap_web/css/tailwind.css` is regenerated on demand by the `/tailwind-rebuild` skill whenever a template edit changes which utility class strings are present. An auto-memory triggers the AI workflow to invoke the skill at the right moment.

#### Implementation

Three artifacts together implement on-demand rebuild:

1. **`tap_web/skills/tailwind-rebuild/SKILL.md`** — procedural skill the AI invokes. Orchestrates `docker/install-tailwindcss.sh` then `docker/tailwind-build`, both inside the running web container via `scripts/dc exec web …`. Documents when to invoke, the verification grep, and the commit-the-artifact step.
2. **`docker/install-tailwindcss.sh`** — installs the pinned binary into `/opt/tailwind/tailwindcss` (backed by the `tailwind_bin` named Docker volume), verifying SHA-256 against `tap_web/third_party_manifest.toml`. Short-circuits in ~50ms when the cached binary's checksum still matches.
3. **Auto-memory** at `memory/feedback_tailwind_class_edit_invoke_rebuild_skill.md` — feedback-type memory that fires when the AI edits any `*.html` under a scanned content path with a diff that adds/removes a class string. Tells the AI to invoke `/tailwind-rebuild` before declaring the task done.

The compiled artifact is committed to git. Production deployments serve it unchanged; dev edits flow through the skill and commit the regenerated artifact alongside the template change.

#### Why this shape (not a container watcher)

An earlier v0 of this requirement was implemented as an always-on container watcher: Dockerfile install of the binary, image-time pre-build, entrypoint one-shot + bash-poll watcher, gitignored output. It worked but the surface area was disproportionate to the problem: ~5 build-time artifacts, DEBUG gating, a poll-loop workaround for the v3.4.17 binary's broken `--watch` and Docker Desktop's missing inotify forwarding, plus a supply-chain spec extension for the build-time binary install. Tearing that out for the skill+memory pattern removes the hoops and matches how the project is actually edited (AI-driven, where memory reliably triggers the skill).

The deliberate trade-off: a human editing without an AI in the loop and without invoking the skill manually reintroduces the original "did I forget to rebuild?" failure mode. The skill's `## When to invoke` section and `docs/misc/doc-dev-tailwind-rebuild.md` document the trigger and recovery so a human can still get it right; the memory guarantees the AI path.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-tailwind-pipeline-rebuild-1 | Rebuild Triggered On Class Change | Implemented | When a template edit adds/removes a Tailwind utility class string, the next-step workflow invokes `/tailwind-rebuild` before completing the task. | Driven by `feedback_tailwind_class_edit_invoke_rebuild_skill.md`. |
| req-web-tailwind-pipeline-rebuild-2 | Rebuild Is Fast | Implemented | The cached-binary skill invocation completes well under a sub-second user-perceived threshold. | ~50ms install short-circuit + ~500ms build. |
| req-web-tailwind-pipeline-rebuild-3 | Compiled Artifact Committed | Implemented | The regenerated `tap_web/static/tap_web/css/tailwind.css` is committed in the same commit as the template change that motivated the rebuild. | Documented in the skill and in the memory's "How to apply" section. |

#### Future

If a human-only editing workflow becomes the dominant mode (no AI in the loop), reintroduce a pre-commit hook or container watcher to close the failure mode that the auto-memory currently covers.


### Content Path Coverage
----
RID: `req-web-tailwind-pipeline-content-paths`

Status: `Implemented`

The Tailwind content-path configuration covers every template directory that ships utility classes.

#### Implementation

`tailwind.config.js` lists three globs:

```js
content: [
  "./tap_web/templates/**/*.html",
  "./tap_viz/templates/**/*.html",
  "./plugins/**/templates/**/*.html",
],
```

All three are static globs the Tailwind CLI resolves directly — no Python plugin discovery is involved at compile time. The skill operates against the same config, so any template edit in the three trees is in scope for the rebuild when the skill is invoked.

#### Development

Plugins increasingly own their own templates and panels. The roscale workbench, samsite KSI scoreboard, samsite nav-links, and any future plugin all sit under the third glob; without it their layout would depend on whatever subset of utilities `tap_web`/`tap_viz` happened to use.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-tailwind-pipeline-content-paths-1 | Plugin Templates Scanned | Implemented | The Tailwind content config includes `plugins/**/templates/**/*.html`. | |
| req-web-tailwind-pipeline-content-paths-2 | Static Glob Resolution | Implemented | The scan path resolves without depending on Python plugin discovery. | |


### Deterministic Output
----
RID: `req-web-tailwind-pipeline-determinism`

Status: `Implemented`

The build pins the Tailwind CLI version so the compiled output is reproducible.

#### Implementation

`tap_web/third_party_manifest.toml` is the single source of truth for the tailwindcss version (`version = "3.4.17"`) and per-arch SHA-256 (`checksum_sha256_linux_x64`, `checksum_sha256_linux_arm64`). `docker/install-tailwindcss.sh` reads both at install time, downloads the matching binary from GitHub Releases, and aborts on checksum mismatch. Two contributors invoking the skill from the same git revision get byte-identical CSS for the same scanned templates because they get byte-identical binaries.

To bump the CLI version: update `version` and both `checksum_sha256_*` fields in the manifest (compute fresh hashes from the upstream release), then on next skill invocation the cached binary's checksum will mismatch and a fresh download + verify will land. Spec + skill text mentioning the version should move together.

#### Development

Tailwind output diffs between CLI versions are real — utility class ordering, vendor prefix sets, and CSS variable patterns can shift. An unpinned build would mean "rebuild the stylesheet" produces a noisy diff that obscures the actual class additions. Pinning + checksum verification also closes the supply-chain hole: a hijacked release on GitHub fails the install rather than silently shipping a different binary under the pinned version.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-tailwind-pipeline-determinism-1 | CLI Version Pinned | Implemented | The Tailwind CLI version used by the build is explicitly pinned in repo configuration. | `version = "3.4.17"` in `tap_web/third_party_manifest.toml`. |
| req-web-tailwind-pipeline-determinism-2 | Reproducible Across Machines | Implemented | Rebuilding from a clean checkout produces a byte-identical `tailwind.css` to a teammate's rebuild. | Modulo node_modules-free standalone binary — no transitive dep drift. |
| req-web-tailwind-pipeline-determinism-3 | Checksum Enforced At Install | Implemented | The install step computes the downloaded binary's SHA-256 and compares against the manifest-pinned value, aborting on mismatch. | Implements `req-grid-thirdparty-manifest.sec-10`. |


### Spawn-Session Integration
----
RID: `req-web-tailwind-pipeline-spawn-integration`

Status: `Implemented`

New session worktrees (per `spec-dev-multisession`) inherit the Tailwind pipeline without per-session setup.

#### Implementation

Every piece of the v1 pipeline — the skill, the install script, the build wrapper, the manifest with pinned checksums, the named-volume declaration in `docker-compose.yml` — lives in tracked files that `spawn-session.sh` already replicates for each session worktree. The session's first relevant template edit triggers the skill (via memory), which downloads the binary into that session's own `tailwind_bin` volume; subsequent invocations short-circuit. No `npm install`, no per-session config, no first-edit surprise.

The auto-memory at `feedback_tailwind_class_edit_invoke_rebuild_skill.md` is global (one copy per user, not per worktree), so AI sessions in any worktree share the same trigger logic.

#### Development

Session worktrees are how the project is actually developed. If the pipeline required per-session setup, the friction would push contributors back to the "ship a hand-built stylesheet, hope it's current" pattern and the gap would re-open.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-tailwind-pipeline-spawn-integration-1 | Spawn Picks Up Pipeline | Implemented | A freshly spawned session worktree has the rebuild path active without extra setup. | Inherent — all pipeline artifacts live in tracked files spawned worktrees clone; first skill invocation per-session populates the named volume. |


### Documented Manual Path
----
RID: `req-web-tailwind-pipeline-manual-fallback`

Status: `Implemented`

A documented manual rebuild path exists for the cases where the skill itself fails, the dev is editing without an AI in the loop, or the rebuild needs to happen outside the container entirely (CI, code review on a machine without Docker).

#### Implementation

`docs/misc/doc-dev-tailwind-rebuild.md` covers: when to rebuild manually (the skill failed, you're editing without AI in the loop, or you're outside the container), how to rebuild (preferred: `scripts/dc exec web /app/docker/install-tailwindcss.sh && scripts/dc exec web /app/docker/tailwind-build` — the same commands the skill runs; fallback for non-container environments: `npx @tailwindcss/cli@3` on the host), how to verify (grep the compiled output for the new class), and the symptom-to-recognize when the rebuild was skipped ("the class appears on the element but the computed style doesn't match").

#### Development

The skill+memory pattern closes the gap for the AI-driven dev loop, but a human editing without an assistant has no automatic trigger. The manual doc is the safety net for that case AND for the genuine-skill-failure case (binary install fails, network issue during download, etc.). Keeping the doc maintained pays off the day someone needs it under pressure.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-tailwind-pipeline-manual-fallback-1 | Doc Exists | Implemented | `docs/misc/doc-dev-tailwind-rebuild.md` documents the manual rebuild flow. | |
| req-web-tailwind-pipeline-manual-fallback-2 | Symptom Documented | Implemented | The doc describes the "class present, no rule" symptom so contributors recognize it on sight. | |
| req-web-tailwind-pipeline-manual-fallback-3 | Recovery Procedures Documented | Implemented | The doc covers what to do when the skill fails and how to rebuild outside the container. | |
