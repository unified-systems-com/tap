---
title: Plugin Release Path — RESOLVED (evicted-plugin promote gap → release-plugin)
date: 2026-07-08
status: resolved
audience:
  - developer
  - llm
spec: tap_plugins/specs/spec-tap-plugin-architecture.md
related_docs:
  - docs/misc/doc-plugin-eviction-plan.md
  - docs/misc/doc-aws-cross-account-activation.md
---

# Plugin Release Path — Decision Pending

## The gap

`scripts/promote-to-main.sh` advances the **monorepo** `origin/main` only. For an
**evicted** plugin (its own git repo; boot installs `{type: git, url, rev, credential}`),
the monorepo `plugins/<slug>/` copy is retained as the "offline dev/test source"
(installed editable by `boot/test_all.boot.json`), while the **real boot**
(`boot/samsite.boot.json`) installs from the pinned git **tag**. So promote-to-main
lands a plugin change in the dev/test copy but **not** in what production boots.

There is **no release automation.** Shipping an evicted-plugin change is a manual
3-step, none of it scripted:

1. Land in the monorepo (`promote-to-main`) — dev/test sees it.
2. Push the plugin tree to its repo + cut a new tag (hatch-vcs derives the version
   from the tag; keep the repo's stripped-`root` pyproject — external repos delete the
   `root="../.."` hatch override the monorepo copy keeps).
3. Bump the `rev` in the consuming boot profile(s) (rides `promote-to-main`; `boot/`
   is monorepo).

**Silent-drift hazard:** promote a plugin change to the monorepo without cutting a
tag → the retained copy runs AHEAD of the tag; dev/test and prod diverge with nothing
flagging it.

## Precedent

`tap-plugin-aws-core` **v0.1.1** (cross-account AssumeRole, 2026-07-06) was released
**direct-to-repo by hand** with explicit OK: clone the repo, apply the changed files
onto it (keeping its stripped pyproject), commit, `git tag`, non-force push `main` +
tag, then bump `samsite.boot.json`'s `rev`. The `gh` token carries scope `repo`, so a
direct `git push` works (no `!` needed). Clean and non-destructive — but manual and
drift-prone at scale.

## The two options (undecided)

**A — Script it; keep the monorepo authoritative (leaning).** Add
`scripts/release-plugin.sh <slug> <version>`: mirror the `plugins/<slug>` subtree to
its repo (keeping the stripped pyproject), tag it, bump the `rev` in the consuming
boot profiles. `promote-to-main` stays monorepo-only (correct — you do NOT want every
commit to move production's pinned rev); releasing stays a deliberate, versioned act.
Add a drift guard: refuse to release if the monorepo tree and the last tag have
diverged unexpectedly. Cheapest edge; kills the drift footgun.

**B — Finish eviction (recipe step 7): delete the monorepo copy.** Then plugin work
happens IN the plugin repo, tested + tagged there; the monorepo carries only the
`rev` bump. Cleaner end state, no dual-source drift — but heavier: needs standalone CI
and the suite-tiers story resolved, and loses the one-repo dev convenience. The
eviction plan explicitly defers this as demand-driven.

Recipe details for both live in `doc-plugin-eviction-plan.md` (per-plugin eviction
recipe + pilot notes).

## Recommendation

Do **A now** (script the release, monorepo authoritative), **B later** when demand
justifies the standalone-CI investment. A is the cheap foundational edge; B is the
expensive one that can wait.

## Resolution (2026-07-09) — `scripts/release-plugin.sh` built under the workspace model

Both options landed, in the order the recommendation set: **A now, B imminent.** The
scripted release exists as `scripts/release-plugin.sh` + `tap/plugin_release.py`
(`req-dev-workspace-release`, `specs/spec-dev-plugin-workspace.md`), built and unit-tested
2026-07-09. It refines option A into the **post-eviction workspace** shape rather than the
monorepo-mirror shape this doc first imagined:

- It operates on the plugin's **own-repo checkout** (editable at `_dev-plugins/<slug>` in a
  `spawn --dev-plugins` workspace), **not** a `plugins/<slug>` monorepo subtree mirror — so it
  is already the option-B end state ("work happens IN the plugin repo") plus a release script,
  which is why building A did not lock us out of B.
- Pre-release guard = `validate_plugin --strict` + the plugin's suite, run **in the harness
  container** against that checkout (refuse-on-red); the immutable-tag guard refuses to move an
  existing `v<version>` tag (kills the silent-drift footgun this doc named).
- The consuming boot-profile `rev` bump is the pure, unit-tested `tap.plugin_release` core;
  **substrate-first** ordering is preserved by bumping every consumer of the released slug on
  each call.

The manual direct-push path (aws_core v0.1.1 precedent) is superseded by this script for any
plugin checked out in a workspace. The full monorepo-copy deletion (option B proper) rides the
coordinated eviction wave (`doc-plugin-eviction-plan.md` Addendum 2026-07-09).

## Status (historical)

Decision pending, not scheduled. Manual direct-push is the current sanctioned path
(used for aws_core v0.1.1); a scripted release is the wanted future.
_(Superseded by the Resolution section above, 2026-07-09.)_
