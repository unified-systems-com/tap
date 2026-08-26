---
title: Plugins Effort — Overnight Close-Out Plan
spec: specs/spec-tap-boot-v0.md
audience:
  - llm
  - developer
status: runbook
---

# Plugins Effort — Overnight Close-Out Plan

The fire-and-forget checklist for the `session/plugins` work discussed this session. George
triggers it once the other sessions have concluded and it is safe to run **last-session-standing**;
Claude executes Phases 0–2 autonomously, leaving the repo green and promoted at each phase boundary.
Phase 3 is a **supervised follow-on**, deliberately out of the autonomous scope (it rewires the
test/promote workflow — human eyes wanted).

## Trigger condition

Do **not** start until ALL of:

1. No sibling session will **land colliding edits on `main`**. The real bar is not "the registry is
   empty" — it is "nothing else will promote a conflicting change." The Phase 2 collision risk is a
   git/merge concern (a wide string-rewrite across tests/fixtures/GRIFT vs. a concurrent edit to the
   same lines, both promoting), NOT a runtime one. A sibling that is **read-only and will be scrapped
   (never promoted)** does not count as a blocker — its changes never reach `main`, so the sweep's
   merge base stays clean. (Confirmed non-blocker 2026-07-02: the `codex-security` session is an
   overnight security scan against its own isolated stack, to be discarded — it does not gate this run.)
2. Resource contention is acceptable. Worktrees are isolated Compose stacks (own DB/ports), so a
   sibling scan can't corrupt the full-lane DB — but both stacks share host CPU/RAM, so a heavy scan
   running concurrently can make the Phase 2/3 lanes slower or flakier (timeouts, not corruption). For
   the cleanest signal, run the heavy lanes when no sibling is peaking; otherwise proceed.
3. George has said go.

## Standing guardrails (apply to every phase)

- **Never promote red.** Each phase gates on a green FULL lane (`scripts/test`) before its promote.
- **Atomic per-phase promote.** Each phase commits + promotes on its own so partial success banks
  value; a later phase failing never un-banks an earlier one.
- **Leave-green-and-report.** If a phase can't reach green after a bounded number of iterations
  (~3 full-lane cycles), STOP: reset to the last green commit, leave the tree clean, write a status
  note (what was attempted, where it stuck, the failing output), and do **not** proceed to a
  dependent phase. Independent later phases may still run only if their preconditions hold.
- **Use `scripts/dc`**, never raw `docker compose`. Validate in-container; the host has no venv.
- **One thing at a time.** Do not interleave Phase 2 and Phase 3 — they both churn tests/profiles.

## Phase 0 — Preflight (gate the whole run)

1. Confirm last-standing (registry + `git branch -r` / sibling worktrees).
2. Merge fresh `origin/main` into `session/plugins`; resolve conflicts.
3. Rebuild + reset: `scripts/dc build web && scripts/dc up -d web` (base compose is pull-only; `dc build` stacks the docker-compose.build.yml overlay), drop stale `test_*` DBs, `scripts/dc exec web uv sync`.
4. **Merge gotchas — main now carries the validation session's dev-validation harness.** Expect and handle:
   - **mypy ratchet trips on merge.** Merging the (un-mypy-gated) `main` history into the gated tree
     reliably flags this session's new files (test-fixture / skill / doc-adjacent noise). Confirm the
     NEW-key diff is noise (`no-untyped-call` in tests, `import-not-found` for un-vendored libs), then
     re-baseline: `scripts/dc exec web uv run python manage.py guards --sync-mypy`.
   - **Validation Map is generated.** If any step below adds/changes a validation surface (a gate step,
     a lane), add its guard (`tap.guards`, one file, carries `slug`/`map_row`/`rid`/`cadence`/`status`/
     `description`) or `DECLARED_SURFACES` entry, then `manage.py guards --sync-map`; the `rid` must
     resolve to a defined requirement. `test_spec_map_in_sync` + `test_guard_rid_resolves` enforce it.
   - **The promote path may now run more.** Cold-boot gate + known-broken manifest + promote-hook are on
     main; check `scripts/promote-to-main.sh` behavior after the merge (it may cold-boot / gate before push).
5. Run the FULL lane (`scripts/test`) on the merged base. **Must be green before touching anything.**
   If red on merge (someone else's breakage), stop and report — do not build on red.

## Phase 1 — Bank the staged work (low risk, do first)

Six commits are already staged + individually verified on `session/plugins`:

- gryphon_playground's plugin-owned standalone-test profile (`plugins/gryphon_playground/gryphon_playground.boot.json`); dropped from samsite
- headless surface-disable backlog (tap_web + tap_api)
- core auth dependency chain fix (`requests` + `django-allauth[socialaccount]`) — surfaced by the
  minimal boot; a real latent-dep fix
- `core` (zero plugins) + `core_dev` (core + grid_fixtures) profiles
- `req-boot-minimal-baseline` spec + `req-tap-plugin-arch-core-packaging` backlog

Steps:

1. FULL lane green (from Phase 0).
2. (Optional, cheap) Live-verify `core_dev` boots — throwaway spawn `--boot core_dev`, confirm health
   + reconciliation `1 == 1`, then despawn. (`core` zero-plugin already live-verified this session.)
3. Promote (`scripts/promote-to-main.sh`).

## Phase 2 — Type-ownership rename sweep (the flagship)

The main event. Execute **`docs/misc/doc-plugin-type-sweep-runbook.md`** verbatim — decisions are
already ratified (2026-07-02): **verbatim prepend `<slug>__<name>` everywhere, no stripping**
(`aws_account → aws_core__aws_account`, edges `NAME → NAME__<slug>`, fedramp bare types prepended,
sigstore `sigstore_`/`rekor_` kept). No ratification step remains.

1. Run order per the runbook: leaves → samsite-consumed producers → `lotr` last. `lotr` now has
   **zero core ripple** (untangle severed it) — a clean per-plugin rename.
2. Context-aware rewrite (NOT blind sed): only `ENTITY_TYPE`/edge-slug *values*, `db_table` values,
   manifest keys, edge endpoints, GRIFT/fixture/expected `type` fields, Gryphon query strings. Leave
   module paths, filenames, class names alone.
3. Cross-plugin ripple: `samsite` consumes aws/github/sigstore/roscale types by string — update in the
   same atomic sweep.
4. Regenerate migrations (table renames), reset the dev DB.
5. FULL lane between iterations; the corpus is the net — a missed reference fails loud. Iterate to green.
6. Flip the type-collision lint `warn-now → fail-CI` (`req-tap-plugin-type-collision-loud`); set
   `req-tap-plugin-type-node-prefix` / `-edge-suffix` → Implemented in `spec-tap-plugin-type-ownership-v0`.
7. One atomic promote.

Sizing: ~90 node + ~77 edge types across 6 plugins, dominated by string-reference substitution the
suite validates. A full night's execute-and-validate — provided it runs uncontended.

## Phase 3 — Minimal baseline flip + lean-boot independence gate

`req-boot-minimal-baseline` ACs 3/4/5. **Decisions ratified 2026-07-02:** default spawn → `core_dev`;
`base` → `test_all` (the union). **No per-plugin profiles, no tiered test runner** — the validation
session's suite-tiers handoff (`~/tap-sessions/validation-creation/docs/misc/doc-dev-validation-suite-tiers-handoff.md`)
establishes why lean *test lanes* are infeasible: pytest discovery is pure file-path (an absent plugin's
test files **hard-error at collection**, no `importorskip`), `test_settings` sees the *installed venv*
not a profile, and some core suites still hardcode plugin fixtures. Conclusion (theirs, and now ours):
**tests = superset (`test_all`), production profiles minimal, bridge via the cold-boot gate.** A
plugin's standalone-test profile is a *plugin-owned* artifact (`plugins/<slug>/*.boot.json`, booted via
`spawn --boot-file`) created only when that plugin needs standalone testing — **zero created now**.

### The high-value piece: lean-boot independence in the cold-boot gate

The cold-boot gate (built, on main — `tap_boot/management/commands/cold_boot_gate.py`) today
`profiles:resolve`s *every* shipped profile but only **full-boots `base`** (`seed:boot-base`). Resolve
does not install+import, and `base` has every plugin — so the gate **would not have caught tonight's
`requests`/`jwt`** import leakage. The precise, cheap, high-value change:

- **Full-boot a LEAN profile on the scratch DB** — add a step (or repoint `seed:boot-base`) that stands
  up `core` (or `core_dev`) with no plugins present, exercising the core import path in isolation. That
  is exactly what catches the `requests`/`jwt` class. Keep a full-profile boot too for seed-path coverage.
- This **touches the validation surface** → follow the handoff's rules: add/adjust the guard
  (`tap.guards` — one file, carries `slug`/`map_row`/`rid`/`cadence`/`status`/`description`) or a
  `DECLARED_SURFACES` entry (`tap/guards/surfaces.py`), then `manage.py guards --sync-map`; the `rid`
  must resolve to a defined requirement. Meta-tests (`test_spec_map_in_sync`, `test_guard_rid_resolves`)
  enforce it. **Coordinate — the gate + Map are the validation session's; extend, don't duplicate.**

### The flip

1. Rename `base → test_all` (the union; its install set is the superset, so pytest discovery finds
   every plugin's tests). Keep `base` as a momentary copy/alias only if needed to avoid mid-flight breakage.
2. Repoint the default spawn/entrypoint `base → core_dev`; update every `"base"` reference
   (`spawn-session.sh` default, `docker/entrypoint.sh` `TAP_BOOT_PROFILE:-base`, the tap_boot tests that
   load/assert `"base"`, docs). The full lane / promote gate runs against a `test_all`-booted container.
3. `scripts/test` is otherwise **unchanged** (still runs the union in one container — the tiered runner
   is deliberately NOT built). Promote; mark `req-boot-minimal-baseline` ACs Implemented.

### Optional stretch — gryphon as its own lane (`req-dev-validation-suite-tiers-1`)

The dominant full-lane time sink is the `gryphon_playground` corpus; `--fast` already excludes it by
path. The principled version = named `core`/`gryphon`/full lanes. The handoff flagged this as blocked on
gryphon being build-baked — **stale**: `BUILD_BAKED_PLUGIN_SLUGS` is empty, gryphon is package-mode, so
it may now be free. Touches the validation surface (guard + Map). Do only if Phases 2–3 land clean with
time to spare. Pairs with `req-dev-validation-suite-tiers`.

## Explicitly NOT in this close-out

- **Full plugin eviction** (monorepo → own repos, authed git-source install) — a separate,
  *supervised* morning plan: `docs/misc/doc-plugin-eviction-plan.md`. Its build prerequisite is now
  **done** (`req-tap-plugin-arch-source-secret` Implemented 2026-07-03 — the `GIT_ASKPASS` authed install
  path); what remains is human-supervised (mint the read-only PAT, push the pilot repo, flip its source),
  which is why it was deliberately NOT in this unattended overnight scope.
- Building the headless toggle (`req-web-rendering-headless` + tap_api) — backlog build, demand-gated.
- Core apps as workspace members (`req-tap-plugin-arch-core-packaging`) — backlog, downstream of
  app-interdependency reduction.
- Slim-install / airgapped wheelhouse — backlog, demand-gated.

## Definition of done

Sequenced, each phase atomically promoted behind a green FULL lane:

- **Phases 0–1:** the core/core_dev profiles + gryphon_playground's plugin-owned profile + the auth-deps fix + the specs on `origin/main`.
- **Phase 2 (flagship):** the type-ownership sweep complete, collision lint flipped to fail-CI.
- **Phase 3:** default → `core_dev`, `base` → `test_all`, and the cold-boot gate full-boots a lean
  profile (the `requests`/`jwt` independence check) — coordinated with the validation conventions.

Phases are ordered by risk/value: bank the staged work, then the sweep, then the baseline flip. If a
phase can't converge, **stop, reset to last green, leave the tree clean, and report** — later phases
run only if their preconditions still hold. Phase 3's flip must not land without the merged tree green.

## Wishlist / smaller follow-ons (not blocking; do if convenient)

- **Shell tab-completion** for `spawn-session.sh` (boot-profile arg → complete against `boot/*.boot.json`
  ids) and `despawn-session.sh` (session-name arg → complete against the `~/tap-sessions/.registry`
  rows). A bash/zsh completion script under `scripts/`, sourced from the shell profile.
- ~~Move `boot/gryphon.boot.json` into `plugins/gryphon_playground/`~~ — **done** (now
  `plugins/gryphon_playground/gryphon_playground.boot.json`, the first plugin-owned standalone-test
  profile; boot via `spawn --boot-file`).
