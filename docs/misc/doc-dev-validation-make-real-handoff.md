# Handoff — make the dev-validation system real

> **BUILT (2026-07-02, session/validation-creation).** The gate-v0 MVP this note
> primed is implemented and verified live: `manage.py cold_boot_gate` (in
> `tap_boot`) driven by `scripts/gate` (fresh scratch DB), the 6-step ordered
> cold-boot cycle (migrate-from-zero → `makemigrations --check` → per-profile
> resolve → strict `base` boot → real-backend collector cycle + PRODUCED_BATCH →
> health), the known-broken manifest (`tap_boot.cold_boot_gate_known_broken.json`,
> seeded empty), and the promote-hook wiring in `scripts/promote-to-main.sh`
> (full pytest lane + cold-boot gate, hard-block, before the atomic push).
> Measured wall-clock ~66–107s. The gate fires a **deterministic offline canary
> collector** (`grid_fixtures:canary`, in the neutral grid_fixtures plugin —
> emits a fixed two-node/one-edge batch with no network/credentials), so the
> real-backend cycle never flakes on an upstream. Deferred (named): `tap/ratchet.py`
> extraction, suite-tiers affected lane, canary-set (`-m smoke`) governance.
> Building it caught + fixed a live break: the collector-identity refactor's stale
> module-path keys survived in `boot/samsite.boot.json` (the demo profile) *and*
> `test_orchestrator.py` (4 red tests on main) — both fixed, both now guarded.
> `specs/spec-dev-validation.md` is authoritative for as-built detail.

Session-priming note for the fresh session that picks up the validation build.
Not authoritative spec (`specs/spec-dev-validation.md` is). Versioning is git.

**Goal:** discuss and then make TAP's development-validation system real — move
`spec-dev-validation.md` from mostly-Proposed to built, scoped deliberately (don't
overbuild; server-side CI is post-July). The keystone is the cold-boot smoke gate +
its promote-path enforcement.

## Ground first (in this order — per the "ground in canon" discipline)

1. **`specs/spec-dev-validation.md`** — the center of gravity. Read every
   requirement + the Validation Map. Status today: `collection-complete` =
   Implemented; ALL others Proposed (map, smoke-gate, real-backend, canary-tier,
   known-broken, promote-hook, ratchet-harness, suite-tiers).
2. **`tap_cares/management/commands/dev_validation_spike.py`** — the Phase-0 spike.
   ALREADY PROVES the load-bearing mechanism: a collector driven through the REAL
   `SteadyQueueBackend` via an in-process drain (dispatch→claim→perform), with teeth
   (`--skip-drain` ⇒ job stays READY ⇒ non-zero exit). Phase 1 wraps this into the
   ordered cold-boot cycle.
3. **`specs/spec-dev-multisession.md` `req-dev-multisession-promote-gate`** — the
   reciprocal. `scripts/promote-to-main.sh` is the wiring point: the gate runs
   between Step 2 (pre-push merge) and Step 3 (atomic push).
4. **`plan/road-products.md`** active step + doctrine (strategic filter).
5. **`docs/misc/doc-dev-validation-enterprise-ci-strategy.md`** — the longer-horizon
   "outside the laptop" sibling (server CI, PR-gated promote, AI-in-pipeline).
   Optional deeper reading; trigger-gated, NOT this scope.
6. MEMORY entry "Validation: xdist lanes + read-only Flaw promoted" — latest state.

## Current state (real vs to-build)

- **REAL:** Validation Map + collection-completeness guard; the ratchet family
  (log-site, authz, direct-write, json-files, gryphon stage+branch); pytest-xdist
  parallel lanes (`scripts/test` full / `--fast`); the `smoke` marker; the Phase-0
  real-backend spike; the read-only-search-write Flaw.
- **TO BUILD (the work):** cold-boot smoke gate (Phase 1), known-broken manifest,
  promote-hook enforcement, ratchet-harness extraction (`tap/ratchet.py` — already
  past its 3rd caller), canary-tier membership discipline, suite-tiers affected lane.

## Prior art already gathered (NetBox + Nautobot — DON'T re-research)

- Both: real Postgres/Redis containers (not mocks) + `makemigrations --check` +
  a consolidated Ruff gate. Neither runs mypy; neither enforces a coverage floor
  (Nautobot has none) — TAP's ratchets are ABOVE their bar.
- Both take the low-fidelity async path (NetBox RQ-inline / Nautobot Celery-eager)
  that upstream docs warn against — TAP's real-backend spike is genuinely ahead.
- Nautobot's invoke-tasks = CI≡local is the gold standard; `scripts/dc` +
  `scripts/test` already lean that way. Steal later (trigger-gated): frozen-dataset
  migration-upgrade test.
- Cheap table-stakes TAP still lacks: `makemigrations --check` (#1 Django gap),
  a dependency scan (pip-audit), pre-commit≡CI mirror.

## Decisions/framing to carry forward

- The gate MUST run inside the compose image, never a reimplemented env.
- **One gate, many invokers:** build it as a SINGLE artifact (`manage.py`
  command or `scripts/gate`) that local + promote + future CI invoke identically.
- Server-CI's real trigger is the TRUST BOUNDARY (a 2nd contributor — human or
  agent — makes "did you run it?" unverifiable); TAP's multi-session AI model may
  have half-fired it. But that's post-July; THIS scope is the LOCAL gate.
- Ratchets are the AI-specific guardrail (they mechanically block the silent
  quality-erosion an agent would otherwise slip in). Frame new mechanisms this way.
- Fold `makemigrations --check` into the cold-boot cycle (cheap asymmetric edge).
- Honest-coverage rule: anything guarded only by "the suite passes" is labeled
  CI-unguarded, by design.

## Motivating data point

The 2026-07-02 clean-path merge caught that `main`'s `base` boot profile was briefly
broken post-package-mode-migration (preboot coherence abort) — a cold-boot gate
running preboot in a rebuilt image would have caught it MECHANICALLY before a spawn.
Second such data point. Use as the scope-setter for "what the gate must exercise."

## Discussion agenda

1. What "real" means for gate v0 — MVP scope (cold-boot cycle + known-broken
   manifest + promote-hook wiring, built on the Phase-0 mechanism)?
2. Gate-as-single-artifact shape: `manage.py` command vs script; how
   `promote-to-main.sh` invokes it; wall-clock budget (fidelity > speed).
3. Known-broken manifest format (follow the house ratcheting-baseline convention).
4. Sequencing: gate first vs extract `tap/ratchet.py` first vs the makemigrations
   edge — and what stays trigger-gated (server CI, frozen-dataset migration test).
5. **Per-profile cold-boot validation (validation in a world of variable plugins).**
   Today the gate/test model is "all plugins installed" — pytest discovery is pure
   file-path (not plugin-aware; no `importorskip` guards, so an absent plugin's
   test files hard-error at collection), and `test_settings` loads whatever is
   editable-installed in the venv (entry-point discovery), NOT a profile. Core
   suites hardcode plugin fixtures (lotr ×22 core-test files, samsite ×5, gryphon
   ×3), and `gryphon_playground` is build-baked (always-on) precisely because the
   Gridkin suite needs it. That's fine for CI correctness, but nothing asserts a
   *minimal* profile (e.g. no gryphon) actually cold-boots and works — the same bug
   class as the 2026-07-02 `base`-profile break (65ab633b "guard all shipped
   profiles"). Decide:
   - The gate should **cold-boot each shipped profile and assert it comes up** (the
     missing axis), rather than making pytest discovery plugin-aware (that fights
     the design and would require de-hardcoding lotr from the core suites).
   - As profiles diverge (lean customer profiles vs. dev), the **test/dev
     environment needs a "full/dev" profile whose install set is the superset**, so
     entry-point discovery still finds every plugin in the test venv (else the
     Gridkin/plugin suites red). Keep tests = "all plugins"; keep production
     profiles minimal; bridge with a dev/full profile + per-profile boot-smoke.
   - Making a plugin profile-optional in production follows the **lotr pattern**
     (package-mode + in a profile's `install`, editable-installed in the test venv);
     `gryphon_playground`'s move off build-baked is gated on the held gryphon-engine
     refactor.

## Session kickoff prompt

Copy-paste to prime the fresh session. This is the discussion agenda above, tightened
into a kickoff; the doc body is the authoritative context.

```
Make TAP's development-validation system real — move spec-dev-validation.md from mostly-Proposed to built,
scoped deliberately (don't overbuild; server-side CI is post-July).

READ FIRST (in this exact order — per "Ground in canon before building"):
1. CLAUDE.md — esp. the multi-session promote workflow, the dev-validation promote gate
   (req-dev-multisession-promote-gate ↔ req-dev-validation-promote-hook), and the security/roadmap filters.
2. docs/misc/doc-dev-validation-make-real-handoff.md — THE priming note for this task. It has the
   ground-first reading order, the real-vs-to-build inventory, prior art already gathered (do NOT
   re-research NetBox/Nautobot), decisions to carry forward, the motivating data point, and the
   discussion agenda. Follow it.
3. specs/spec-dev-validation.md — the authoritative spec + the Validation Map. Read every requirement.
   Status today: collection-complete = Implemented; ALL others Proposed.
4. tap_cares/management/commands/dev_validation_spike.py — the Phase-0 spike. It ALREADY proves the
   load-bearing mechanism (a collector driven through the REAL SteadyQueueBackend via in-process drain,
   with teeth). Phase 1 wraps this into the ordered cold-boot cycle.
5. docs/misc/doc-dev-validation-enterprise-ci-strategy.md — longer-horizon sibling (server CI, PR-gated
   promote). Trigger-gated, NOT this scope — read for framing only.

WHAT'S ALREADY REAL (don't rebuild): Validation Map + collection-completeness guard; the ratchet family
(log-site, authz, direct-write, json-files, gryphon stage+branch); pytest-xdist lanes (scripts/test
full / --fast); the `smoke` marker; the Phase-0 real-backend spike; the read-only-search-write Flaw.

THE WORK (discuss scope with me first, then build): the cold-boot smoke gate (Phase 1, built on the
Phase-0 mechanism), known-broken manifest (house ratcheting-baseline convention), promote-hook
enforcement wired into scripts/promote-to-main.sh (between pre-push merge and atomic push),
ratchet-harness extraction (tap/ratchet.py — already past its 3rd caller), per-profile cold-boot
validation, and fold `makemigrations --check` into the cold-boot cycle (the #1 Django gap both
exemplars close and TAP doesn't).

LOAD-BEARING FRAMING:
  - ONE gate, MANY invokers: build the gate as a SINGLE artifact (manage.py command or scripts/gate)
    that local + promote + future CI invoke identically. Not "CI reimplements what I run locally."
  - The gate MUST run inside the compose image, never a reimplemented env (the container Python is
    non-stock). Fidelity > speed.
  - Ratchets are the AI-specific guardrail (they mechanically block silent quality erosion). Frame new
    honesty mechanisms this way.
  - Honest-coverage rule: anything guarded only by "the suite passes" is labeled CI-unguarded by design.
  - Adding ANY validation surface requires adding its Validation Map row in the same change
    (spec-dev-validation.md is the center of gravity).

MOTIVATING DATA POINT: the 2026-07-02 clean-path merge caught that main's `base` boot profile was
briefly broken post-package-mode-migration (preboot coherence abort). A cold-boot gate running preboot
in a rebuilt image would have caught it MECHANICALLY before a spawn. That's the scope-setter for "what
the gate must exercise."

Start by grounding in the reading list, then propose the gate-v0 MVP scope (agenda item 1 in the handoff
note) before writing code — I want to agree on scope first.
```
</content>
