---
title: Guard Meta-Integrity — Protecting the Gates from Being Disabled
spec: specs/spec-dev-validation.md
audience:
  - developer
  - llm
covers:
  - req-dev-validation-meta-integrity
  - req-dev-validation-meta-integrity-1
  - req-dev-validation-meta-integrity-2
  - req-dev-validation-meta-integrity-3
  - req-dev-validation-meta-integrity-4
update-triggers:
  - The CODEOWNERS machinery path set changes (a new scanner engine, a new gate script, a moved file)
  - The branch-protection / required-check settings change, or the code-owner changes
  - The guard-integrity guard or the guard manifest changes shape
  - A new self-safe direction is recognized, or the machinery/data seam is re-drawn
  - Meta-integrity graduates to its own spec (update `spec:` and this note)
assumes:
  - Reader understands the guard system itself — see doc-dev-validation-guard-system.md
  - Reader is changing a guard, the harness, the CI/gate config, or the branch-protection settings
provides: |
  The operational how-to for the "who guards the guards" layer: what is protected and
  why, the machinery-vs-data seam, the two enforcement layers (in-repo loud + out-of-band
  block), the exact branch-protection settings to apply, and the procedures for the changes
  that touch protected surfaces — adding/removing a guard, changing the machinery, moving a
  baseline. After reading, you can make a legitimate change to the validation system without
  tripping the integrity controls, and you know why a tripped control is telling the truth.
status: reference
---

# Guard Meta-Integrity — Protecting the Gates from Being Disabled

> Owning spec: [`specs/spec-dev-validation.md`](../specs/spec-dev-validation.md) § *Guard-System Meta-Integrity* (`req-dev-validation-meta-integrity`). Companion to [`doc-dev-validation-guard-system.md`](doc-dev-validation-guard-system.md), which explains the guard system this layer protects.

## What this is

The guard system enforces invariants about TAP. This layer enforces one invariant about the *guard system itself*: **it must resist being disabled by a code push** — accidentally or intentionally. That is the "who guards the guards" problem, and its answer is two-layered:

- **In-repo controls make tampering _loud_** — a neutered or deleted guard fails CI fast.
- **Out-of-band platform controls make tampering _blocked_** — branch protection + `CODEOWNERS`, which a code push cannot edit.

You need both, and the second is load-bearing: no in-repo check can ultimately protect itself, because the same push that weakens a guard can weaken its self-check.

## The threat, briefly

A gate can be neutralized many ways: neuter a `check()` to `pass`; broaden an allowlist; delete a guard module; land a real violation and its baseline line in one commit; or — the softest, highest-leverage move — **stop running the suite at all** by editing the runner, the CI workflow, the gate scripts, or the pytest config. That last class dominates: it touches no guard, it just removes them from the critical path, and it collapses every in-repo self-check at once (they all fire only if the suite runs).

## The seam: machinery vs. data

Changes are governed by the **direction** they move, not merely by file type.

| | What | Rule |
| --- | --- | --- |
| **Machinery** | The harness & bases (`tap/guards/**` except baselines), scanner engines (`tap/source_scan.py`, `tap/direct_write_coverage.py`, `tap/authz_coverage.py`, every `**/guards/**`), the ratchet core (`tap/ratchet.py`), the Map generator & declared surfaces (`tap/guards/report.py`, `tap/guards/surfaces.py`), the runner & honesty meta-tests (`tap/tests/test_guards.py`), the CI/gate config (`.github/**`, `ci/terraform/**`, `scripts/gate*`, `scripts/promote*`), the test config (`pyproject.toml`), **and the allowlists/vocabularies embedded inside guard modules**. | **Review-always** (owned in `CODEOWNERS`). |
| **Self-safe data** | A ratchet **baseline shrinking**; a change that **adds coverage** (a new guard, a new declared surface, a new Map row). | **Open** — no special gate. |

Everything that *removes* or *loosens* is a weakening move and sits on the review-always side. The intuition that "the lists and maps grow and shift" holds for coverage-adding growth; it does **not** extend to growing an allowlist or an exemption set — that is loosening.

## Layer 1 — in-repo, makes tampering loud

- **The guard-integrity guard** (`tap/guards/guard_integrity.py`, `req-…-meta-integrity-3`) asserts two things the other meta-tests miss:
  - every slug in the committed floor `tap/guards/guard_manifest.txt` is still discovered (catches a **removal or rename**), and
  - no discovered guard's `check()` is a no-op — `pass` / `return` / `...` / `assert True` (catches a **neutered** guard, which `test_spec_map_in_sync` cannot see because the Map row is unchanged).
  - It floors *itself*, and it is recursive: the harness and meta-tests are machinery, so weakening them is a machinery edit.
- **The existing honesty meta-tests** (`test_guards.py`) are the rest of this layer: `test_spec_map_in_sync` (a deletion changes the generated Map), `test_guard_rid_resolves` (no guard points at a fake requirement), and the ratchet's own stale-entry tooth (a fabricated baseline line, or a ratchet neutered via `measure()` → empty set, fails because its baseline entries go stale).

## Layer 2 — out-of-band, makes tampering blocked

`.github/CODEOWNERS` marks the machinery paths as owned by the sole code-owner (`@notgeorge`). This is **inert until the branch-protection settings are applied**, because CODEOWNERS is only enforced when GitHub is told to require code-owner review. In **repo Settings → Branches → branch protection rule for `main`**:

1. **Require a pull request before merging** → check **Require review from Code Owners**. *(This is the switch that makes CODEOWNERS bite.)*
2. **Require status checks to pass** → add the **`gate`** aggregator job as the one required check (the `line` matrix names — `test_all`, `core_ci`, `samsite` — change with the matrix and are required *through* `gate`, never directly); check **Require branches to be up to date**.
3. **Do not allow bypassing the above** — make any escape hatch deliberate.
4. Confirm **`@notgeorge` resolves** (George's username; since 2026-08-08 the repo lives in the `unified-systems-com` org, where he is owner). GitHub **silently ignores** an owner it cannot resolve, so if code-owner review ever seems to do nothing, check this first.

Together: an edit to a workflow that drops the guard lane cannot self-authorize, because the required-check contract lives in repo *settings*, not in a file the PR can touch.

## Operating it — procedures

- **Add a guard** — drop the module in a `guards/` folder, define its spec requirement, run `manage.py guards --sync-map`, commit. **No manifest edit needed** (coverage-adding is the safe direction).
- **Remove or rename a guard** — remove/adjust its slug in `tap/guards/guard_manifest.txt` (a `CODEOWNERS`-gated machinery change) *and* run `--sync-map`. The integrity guard fails until the manifest matches; that failure is the system forcing the removal to be an explicit, reviewed act.
- **Change the machinery** (harness, scanner, runner, CI/gate config) — expect it to require the code-owner's review. That friction is the point.
- **Shrink a ratchet baseline** — free; do it whenever you fix a flagged item.
- **Grow an allowlist / add an exemption / add a `# TAP-*-COV` tag site** — this is a *weakening* move; it lives in machinery (the guard module) and is reviewed. Prefer fixing the underlying issue.
- **When the guard-integrity guard fails** — read the message. "manifest guard(s) no longer discovered" means a floored guard was removed/renamed (fix the manifest if intentional, or restore the guard). "trivial no-op check()" means a guard was gutted (restore its real body).

## Honest limits

Stated, not implied (`req-…-meta-integrity-4`):

- A repo **admin can bypass branch protection.** Trust reduces to the admin set; these controls make disabling a gate a deliberate, logged, reviewed act — not an impossible one. For the solo / pre-customer phase, that is the right calibration.
- The **violation-and-baseline-in-one-commit** hole is not closeable by the ratchet alone; it relies on PR review (which happens anyway).
- The **self-protection regress** is real: any in-repo layer can be edited by whoever can merge; only the out-of-band anchor actually blocks, and only as far as the admin set is trusted.

## Status

The in-repo layer (the guard-integrity guard) and `.github/CODEOWNERS` are **built**. The branch-protection **settings** (Layer 2's teeth) are the remaining step — applied in the repo admin UI, not in-repo. Until they are on, this system is tamper-*evident*, not tamper-*blocked*. See the spec for the full requirement family and its status.
