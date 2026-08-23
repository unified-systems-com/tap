# Plugin Development Workspace

## Philosophy

Once plugins leave the monorepo (see `doc-plugin-eviction-plan.md` and
`spec-tap-plugin-external-development.md`), TAP core is a **core-only repository** and every
plugin lives in its own git repo. This spec defines how anyone — the TAP team first, then
external developers — actually *develops* a plugin in that world: the **plugin workspace**.

The governing constraint is **one way to develop any plugin**, and we develop ours the exact
way an external developer will. That dogfooding is the point: the friction we feel is the
friction we fix before Aug-1, and there is no second, privileged inner loop that hides it.

The workspace is deliberately thin. It is a clone of core used as a **harness** plus a set of
editable plugin checkouts plus the rest git-installed at pinned tags, booted as one mixed
profile. The prior art is `go work` and uv's `tool.uv.sources` overrides ("local checkout for
these, pinned for the rest") and Cargo `[patch]`; we are on uv, so we lean on its native
editable / source-override support and keep the TAP layer a thin integration over spawn +
boot profiles, not a new package manager.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | One loop | The TAP team and external developers use the identical develop→test→release loop. |
| 2. | Mixed source | A workspace boots N editable plugins under active edit against the rest pinned at tags. |
| 3. | Thin over uv | Reuse uv's native editable/source overrides + existing boot source types; invent as little as possible. |
| 4. | Scripted release | A plugin release is one command (tag + bump consuming profiles), not a hand-typed sequence. |
| 5. | Coupled changes | A cross-plugin change is the same mechanism (both editable in one workspace), not a special case. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-workspace-model | [The Workspace Model](#the-workspace-model) | Implemented | Harness (core clone) + editable dev plugins + rest git-pinned, booted as one mixed profile. Proven 2026-07-09: a real `--dev-plugins compliance_core` spawn booted healthy. |
| req-dev-workspace-spawn | [Spawning A Workspace](#spawning-a-workspace) | Implemented | `spawn-session --dev-plugins <slugs>` resolves each slug against the base profile, clones it editable, pins the rest. `tap/dev_workspace.py` + spawn wiring. |
| req-dev-workspace-loop | [The Inner Loop](#the-inner-loop) | Proposed | edit → relevance-gated test → `validate_plugin` → release, all against the running workspace. |
| req-dev-workspace-release | [Scripted Plugin Release](#scripted-plugin-release) | Implemented | `release-plugin` tags the repo and bumps consuming boot profiles, substrate-first. `scripts/release-plugin.sh` + `tap/plugin_release.py`, built 2026-07-09. |
| req-dev-workspace-coupled | [Coupled Cross-Plugin Changes](#coupled-cross-plugin-changes) | Proposed | Two coupled plugins checked out editable together; released in dependency order. |
| req-dev-workspace-uv-native | [Lean On uv Native Sources](#lean-on-uv-native-sources) | Proposed | Editable/pinned selection uses uv's own source mechanism; TAP integrates, does not reinvent. |
| req-dev-workspace-nongoals | [Non-Goals](#non-goals) | Proposed | Registry, multi-workspace orchestration, and generator scaffolding are out of scope here. |

### The Workspace Model
----
RID: `req-dev-workspace-model`
Status: `Implemented`

#### Status Details
Proven 2026-07-09: `spawn-session wsdev samsite --dev-plugins compliance_core` booted healthy —
`compliance_core` installed editable from `_dev-plugins/compliance_core` (`direct_url.json`
`editable: true`) while `fedramp_20x_ksi` stayed git-pinned at `v0.2.0`, and both the conformance
gate (12 plugins) and the compatibility gate fired at standup.

**2026-08-09 (later the same day):** the samsite record re-homed into `tap-plugin-samsite`
(`req-boot-bootstrap-samsite-rehome`), which briefly left `--dev-plugins` requiring a repo-local
base while `--from` was mutually exclusive with it. That seam is now closed: `--from` composes
with `--dev-plugins` (`req-dev-workspace-spawn-6`) — the pointer's stage-0-staged record becomes
the base profile the workspace derivation overrides, so the external-adopter dev flow is one
command:

```
scripts/spawn-session.sh sam-dev cli \
  --from git+https://github.com/unified-systems-com/tap-plugin-samsite@v0.2.0#samsite \
  --dev-plugins samsite
```

A **plugin workspace** is the unit of plugin development. It is composed of:

- **the harness** — a clone of the core TAP repo (a session worktree today; see
  `spec-dev-multisession.md`). Core is present in full, including specs and tests, because a
  developer's coding agents need them. Core is *not* installed as a package — it is the
  harness the plugins load into.
- **the dev plugins** — one or more plugin repos checked out **editable** because they are
  under active edit, **nested under the harness worktree at `_dev-plugins/<slug>/`** (a
  gitignored path, so the harness repo never tracks them). Their code is live-mounted; edits
  take effect on reload/reboot without a release. (Nested is the first-cut choice — decided
  2026-07-09 — for a self-contained, trivially-cleaned-up workspace; sibling-checkout reuse
  across workspaces is a later option if nesting proves limiting.)
- **the pinned rest** — every other plugin the booted profile needs, git-installed at a
  pinned tag via the read-only `github-plugins-ro` credential (the eviction install path).

The workspace boots **one mixed editable+git profile** against this composition. Mixed-source
boot is proven: the 2026-07-09 samsite verify booted 8 git-pinned + 4 editable plugins healthy.
`editable` and `git` are existing boot source types (`spec-tap-boot-v0.md`); the workspace does
not add a source type, it composes the two.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-workspace-model-1 | Harness Is A Core Clone | Proposed | The harness is a full core checkout (specs + tests included), not a packaged core. | Reuses the session worktree. |
| req-dev-workspace-model-2 | Dev Plugins Editable | Proposed | Plugins under active edit are checked out editable; edits need no release to take effect. | |
| req-dev-workspace-model-3 | Rest Pinned | Proposed | All other required plugins are git-installed at pinned tags via `github-plugins-ro`. | |
| req-dev-workspace-model-4 | One Mixed Profile | Proposed | The workspace boots a single profile mixing editable and git sources. | Composes existing source types; adds none. |

### Spawning A Workspace
----
RID: `req-dev-workspace-spawn`
Status: `Implemented`

#### Status Details
Implemented as `tap/dev_workspace.py` (pure stdlib, host-runnable venv-free, reusing
`tap.boot_pointer`'s credential + `GIT_ASKPASS` helpers) + `spawn-session.sh --dev-plugins`
wiring (mirrors `--from`). Unit-tested (`tap/tests/test_dev_workspace.py`) and proven by a real
spawn (see `req-dev-workspace-model` Status Details). Since 2026-08-09 the base may take any of
**three forms**, staged before the derivation runs so the staged record IS the base profile — no
change to the derivation itself: a repo-local profile (positional/`--boot`), a `--from` pointer
(`req-dev-workspace-spawn-6`, stage-0 fetched + digest-verified — the durable/versioned tier), or
a `--boot-file` path (`req-dev-workspace-spawn-7`, staged as-is under its basename id — the
trusted-local-file tier, serving the fork-cutover dev flow: an adopter edits their fork's
in-package record to point the dev slug at their own repo with rev-as-BRANCH, and works editable
against it with no release/digest ceremony; `clone_editable` resolves branch revs).

`spawn-session.sh` gains a `--dev-plugins <slug[,slug...]>` option that stands up a workspace
in one command, extending the existing spawn lifecycle (`req-dev-multisession-spawn-script`).

Each `--dev-plugins` slug is a **selector into the base profile's `install` list**, not a
source in itself. The **boot profile is the authority** for where a plugin comes from: every git
install entry already carries the exact `source.url`, `source.rev`, and `source.credential`.
Spawn resolves each named slug to its base-profile entry and clones **that exact repo at that
rev, authed with that credential**, into `_dev-plugins/<slug>/` under the harness worktree, then
flips only that entry's `source` from `git` → `editable` (path → the nested checkout) while every
other plugin stays `git` at its pinned tag. It boots the resulting profile through the normal
spawn path.

The slug is deliberately **not** used to *derive* a URL. A naming convention exists
(`dist_name_for_slug` → `tap-plugin-<slug-dashed>` → a repo), but deriving from it would hardcode
the org/naming and break on forks, renames, and private product repos in other orgs — exactly the
cases the explicit boot-record `url`/`credential` exist to handle. A `--dev-plugins` slug that is
**not present in the base profile is an error** (there is nothing to resolve or override), not a
fall-back to a guessed URL.

`_dev-plugins/` is gitignored in core so the harness never tracks the nested checkouts, and
despawn removes the whole worktree (nested checkouts included) — self-contained cleanup. The
derived profile `boot/<base>__dev.boot.json` is gitignored for the same reason: it is generated
from a committed base and points at `_dev-plugins/` paths that exist in exactly one developer's
worktree, so committing it would ship an unbootable profile.

**The workspace must not change what the core lane tests.** `_dev-plugins/` is excluded from core
pytest collection (an `--ignore=` in `addopts` mirrored in the `_IGNORED_DIRS` ledger,
`req-dev-validation-collection-complete`). Without that, standing up a workspace silently widens
the core suite to include whichever plugin repos happen to be checked out — so the lane's result
would depend on developer-local state, and a plugin repo's own conftest (written against its own
layout) can break the core run outright. Excluding them makes the workspace lane behave exactly
like a normal session, where those same plugins are git-installed into the already-pruned `.venv`.
A dev plugin's tests are gated where they belong: its own repo CI, and `release-plugin.sh`'s
pre-release gate (`pytest --pyargs tap_plugin.<slug>`), which is why that gate requires tests to
live IN the package.

`--dev-plugins` composes with a base that names the full plugin set and pinned revs;
`--dev-plugins` overrides the named subset to editable. The base is either a **repo-local
profile** (positional/`--boot`) or a **`--from` bootstrap pointer** (`spec-tap-boot-bootstrap.md`):
spawn stages the pointer's record into the worktree's `boot/` first (stage-0 fetch +
digest verification), then runs the same derivation over the staged record — the derivation
code reads `boot/<id>.boot.json` by id and never knows whether the base was committed or
staged. The trust decision, stated once: the pointer's digest verification happens at fetch
time against the record **as shipped**; the derived `__dev` workspace profile is a
post-verification **local mutation**, identical in kind to what the repo-local flow already
does. Nothing new is trusted. A bare `--dev-plugins` with no base at all is an error (there
is no install list to select from), matching the slug-absent fail-closed posture.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-workspace-spawn-1 | Flag Exists | Proposed | `spawn-session.sh --dev-plugins <slugs>` stands up a workspace. | Extends the spawn script. |
| req-dev-workspace-spawn-2 | Editable Checkout Ensured | Proposed | Each named plugin is cloned as an editable checkout at `_dev-plugins/<slug>/` under the harness worktree (gitignored); despawn removes it with the worktree. | |
| req-dev-workspace-spawn-5 | Profile Is The Source Authority | Proposed | The slug resolves against the base profile's git install entry for the authoritative `url`/`rev`/`credential`; the slug is never used to *derive* a URL. A slug absent from the base profile is an error, not a guessed clone. | Handles forks, renames, and cross-org product repos. |
| req-dev-workspace-spawn-3 | Rest Stay Pinned | Proposed | Non-named plugins in the base profile remain git-pinned at their tags. | The override is the named subset only. |
| req-dev-workspace-spawn-4 | Composes With A Base Profile | Proposed | `--dev-plugins` overrides a base profile's named subset to editable; bare use (no base at all) is an error, not a silent default. | |
| req-dev-workspace-spawn-6 | Composes With A Pointer Base | Implemented | `--dev-plugins` composes with `--from <pointer>`: the stage-0-staged (digest-verified) record is the base profile; the derivation runs over it unchanged, and a slug absent from the pointed-at record fails with the same slug-absent error. | Built 2026-08-09; closes the samsite-rehome residual. |
| req-dev-workspace-spawn-7 | Composes With A Boot-File Base | Implemented | `--dev-plugins` composes with `--boot-file <path>`: the file is staged as-is under its basename id (the trusted-local-file tier — no digest ceremony by existing contract) and the derivation runs over it unchanged; a `rev` naming a branch clones at that branch (the fork-cutover dev flow). | Built 2026-08-10; the everyday tier beside spawn-6's versioned one. |

### The Inner Loop
----
RID: `req-dev-workspace-loop`
Status: `Proposed`

The develop loop against a running workspace:

1. **edit** the editable dev plugin(s);
2. **test** with `scripts/test`, relevance-gated to the plugin set (`req-dev-validation-suite-tiers`)
   so the inner loop runs the affected plugins' suites, not the whole corpus;
3. **validate** with `validate_plugin --strict` (the conformance gate,
   `req-tap-plugin-extdev-conformance`) — the same admission check the plugin's own CI runs;
4. **release** with `release-plugin` when green (`req-dev-workspace-release`).

Steps 2–3 are the identical entrypoints the reusable per-repo CI runs
(`req-tap-plugin-extdev-repo-ci`), so local green and CI green mean the same thing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-workspace-loop-1 | Relevance-Gated Test | Proposed | `scripts/test` runs the affected plugin set in the inner loop. | Reuses corpus relevance-gating. |
| req-dev-workspace-loop-2 | Local == CI Entrypoint | Proposed | The local validate/test entrypoints are the ones the per-repo CI runs. | No divergent local-only path. |

### Scripted Plugin Release
----
RID: `req-dev-workspace-release`
Status: `Implemented`

A plugin release is one command. `release-plugin <slug> <version>` closes the "no promote
equivalent for evicted plugins" gap (today's evicted-plugin release is a hand-typed
push + tag + boot-rev bump, which silently drifts if the tag step is skipped).

`release-plugin` performs, for the plugin repo:

- run the conformance gate (`validate_plugin --strict`) + the plugin's tests as a pre-release
  guard (refuse to release red);
- commit/push the plugin repo and create the immutable `v<version>` tag (a **signed** tag once
  `req-tap-plugin-extdev-signing` lands);
- bump every consuming boot profile's pinned rev for that slug to `v<version>` —
  **substrate-first**: a substrate plugin (e.g. `compliance_core`) is released and its consumers'
  pins bumped before the consumers themselves release, so dependency order holds.

It is the plugin-repo analogue of `promote-to-main.sh` (which is monorepo-only). The deployment
boot profiles under `boot/` are the bill of materials it edits; those profile records carry no
inline integrity hash (that guard is for *in-package* boot records, one level up — see
`tap.boot_records`), so the bump is a plain, derivation-driven JSON edit, and the git-sourced
`test_all` CI lane booting the resulting profile is what keeps the pins honest end-to-end.

Status Details (Implemented 2026-07-09): `scripts/release-plugin.sh` orchestrates the guard →
tag → bump flow; the pure, host-runnable pin-bump core is `tap/plugin_release.py` (stdlib-only,
like `tap.dev_workspace`), unit-tested in `tap/tests/test_plugin_release.py`. Conformance + the
plugin suite run **in the harness container** against the editable checkout at
`/app/_dev-plugins/<slug>` (the plugin's real install environment); the immutable-tag and
clean-tree guards refuse a red or drifting release; `--dry-run` reports the tag/push/bump without
side effects. Signing (`req-dev-workspace-release-4`'s signed-tag half) rides
`req-tap-plugin-extdev-signing`, deferred to the GitHub-org refactor.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-workspace-release-1 | One Command | Implemented | `release-plugin <slug> <version>` tags the repo and bumps consuming profiles. | Closes the hand-typed-release drift gap. |
| req-dev-workspace-release-2 | Pre-Release Guard | Implemented | Release refuses if the conformance gate or the plugin's tests are red. | Same gate as CI; runs in-container against the editable checkout. |
| req-dev-workspace-release-3 | Substrate-First Ordering | Implemented | A substrate plugin releases and its consumers' pins bump before the consumers release. | Each call bumps every consumer of the released slug; operator releases substrate-first. |
| req-dev-workspace-release-4 | Immutable Tag | Implemented | The release creates an immutable `v<version>` tag (signed once signing lands). | Unsigned tag built; refuses to move an existing tag. Signing ties to `req-tap-plugin-extdev-signing`. |

### Coupled Cross-Plugin Changes
----
RID: `req-dev-workspace-coupled`
Status: `Proposed`

A change that spans two plugins (e.g. a `compliance_core` contract change and its
`fedramp_20x_ksi` consumer) is **not** a special case. Both plugins are checked out editable in
one workspace (`--dev-plugins compliance_core,fedramp_20x_ksi`), developed and tested together as
a unit against the running harness, and released in dependency order via `release-plugin`
(substrate first). The single mechanism — editable-together, release-in-order — replaces any need
for coordinated cross-repo branches or a monorepo atomic commit.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-workspace-coupled-1 | Both Editable Together | Proposed | A coupled change checks out both plugins editable in one workspace. | `--dev-plugins a,b`. |
| req-dev-workspace-coupled-2 | Released In Order | Proposed | The coupled plugins release substrate-first via `release-plugin`. | Reuses release ordering. |

### Lean On uv Native Sources
----
RID: `req-dev-workspace-uv-native`
Status: `Proposed`

The editable-vs-pinned selection is expressed through **uv's own** source mechanism (editable
installs / `tool.uv.sources` overrides), not a bespoke TAP resolver. The TAP layer's job is to
*generate* the right uv/boot configuration from `--dev-plugins` + the base profile and to
integrate it with spawn and boot — it does not re-implement dependency resolution, version
solving, or locking. This keeps the workspace a thin, debuggable layer over a tool developers
already trust, and means uv improvements accrue for free.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-workspace-uv-native-1 | uv Owns Resolution | Proposed | Editable/pinned selection and solving are uv's; TAP generates config, not a resolver. | |
| req-dev-workspace-uv-native-2 | Existing Source Types | Proposed | The boot profile uses the existing `editable`/`git` source types only. | No new source type. |

### Non-Goals
----
RID: `req-dev-workspace-nongoals`
Status: `Proposed`

Out of scope for the workspace loop (owned elsewhere or deferred):

- a **plugin registry / marketplace** — distribution is git-repo-per-plugin + boot-record pins
  (`spec-tap-plugin-external-development.md` non-goals);
- a **scaffolding generator** (`tap new-plugin`) — the plugin-creation skill fills this today;
  a first-class generator is deferred;
- **multi-workspace orchestration** — running many workspaces at once is just repeated spawn;
  no new orchestration layer;
- **CI authoring** — the per-repo CI is `spec-tap-plugin-external-development.md`
  (`req-tap-plugin-extdev-repo-ci`); the workspace consumes it, does not define it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-workspace-nongoals-1 | Named Deferrals | Proposed | Registry, generator, multi-workspace orchestration, and CI authoring are explicitly out of scope here. | Each owned elsewhere or deferred. |
