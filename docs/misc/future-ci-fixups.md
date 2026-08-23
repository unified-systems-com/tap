# Future CI fixups — the named remainder after the 2026-08-09/10 waves

Working notes, not a spec: each item's *contract* lives with the owning spec/RID named
inline; this doc exists so the queue survives session close-outs in one findable place.
Context: the boot-observability, unified-spawn, pull-first, required-secrets, and
samsite-rehome waves (all on main) closed most of the plugin-testing seam — samsite is
the worked pilot for the per-repo CI pattern (caller + nightly depth profile, first run
green both jobs) and the product-line lane cold-resolves the fetched record. What
remains, cost-ordered-ish:

## 1. Plugin-repo CI callers for the remaining repos

Every `tap-plugin-*` repo gets the thin caller invoking core's reusable
`plugin-ci.yml@main` (`req-tap-plugin-extdev-repo-ci`). Two worked templates exist: a
**leaf** (`tap-plugin-grid-fixtures` — conformance only, no `boot_profile`) and a
**stack-needing plugin** (`tap-plugin-samsite` — passes `boot_profile:
ci/nightly.boot.json`, opting into boot-and-test). Copy the matching template into each
repo; ~10 remain. Zero secrets (org is public). Until a repo has its caller, its
shipped suite runs only on the nightly's shallow conformance leg — the
"evicted plugin tests silently gate nothing" trap, half-open.

## 2. Nightly depth profiles (`ci/nightly.boot.json`)

Repos shipping this file opt into the nightly's full boot-and-test leg
(`nightly-plugins.yml` checks for it at discovery). samsite's is the worked template:
the shipped record's sibling closure at the same pins, the plugin-under-test flipped to
`{"type": "editable", "path": "_external/<slug>"}`, seed-only population (empty-secrets
CI ⇒ no fire-collector steps ⇒ no `required_secrets`). `tap-plugin-aws-core` was the
originally-planned pilot (unified session queue) and is the natural next; leaves may
not need one at all.

## 3. `requires_tap` compatibility floors

Enforcement is fully built and checking an empty set: the pre-boot compatibility gate
logs `0 plugin(s) with a requires_tap floor satisfied`, `validate_plugin --strict`
recommends declaring, and plugin-ci's pinned harness is the version checked against.
No plugin declares one. The work is one line per `tap-plugin.toml`
(`requires_tap = ">=0.1,<0.2"`) plus a release each — but choosing honest ranges wants
the small companion decision of a core version-bump convention (when does core bump
minor vs major), or the ranges are guesses. Silent break → loud boot-time refusal.
Model context: the two-mains prior-art sweep (P1, cheapest edge).

## 4. CI for `tap-build-dependencies`

The re-homed `aws_secrets_source` provider's 6 tests run nowhere on push. It is not a
TAP plugin (deliberately — the nightly matrix's first run flagged exactly that), so the
plugin-ci caller does not fit; it needs a plain pytest workflow of its own.

## 5. `validate_plugin --level runs` is unusable (MissingActor)

`--level runs` (service-layer smoke with rollback) fails with
`MissingActor: no named actor for capability 'grid.write'` — confirmed pre-existing via
a control run against released plugin content, not any branch's fault. The runs-level
smoke needs an actor bound around its service calls (compare how boot binds
`tap_bootloader` for population). Until fixed, `--strict --level loads` is the honest
maximum for release gating; the samsite v0.2.0 gate was run at that level.

## 6. `--dev-plugins` / `--from` mutual exclusion — RESOLVED 2026-08-09

Closed the same day it was named: `--from` now composes with `--dev-plugins`
(`req-dev-workspace-spawn-6`, `spec-dev-plugin-workspace.md`) — spawn stages the
pointer's record first, then the existing workspace derivation runs over the staged
record as its base. The external-adopter invocation:
`spawn-session.sh sam-dev cli --from git+…tap-plugin-samsite@v0.2.0#samsite --dev-plugins samsite`.
Remaining tail (not this item): the samsite plugin README's Known Limitation blurb
should be refreshed at the plugin's next release.

## 7. Release-sweep blindness to in-package records

`tap/plugin_release`'s consumer-bump sweep rewrites git pins in repo-local
`boot/*.boot.json` only — it cannot see in-package boot records, so a substrate release
(e.g. aws-core v0.4.0) does not auto-bump the pins inside `tap-plugin-samsite`'s
record; that was hand-advanced during the rehome. As more records re-home, the sweep
needs a plugin-repo-aware leg (or the release procedure grows a manual checklist item
per record-shipping plugin). Named in the rehome's report and
`req-boot-bootstrap-samsite-rehome`'s neighborhood.

## 8. gate-lean diagnostic capture bug

On one 2026-08-09 red, `gate-lean` failed to write its `*-diag.log` (a stale capture
from an earlier run survived instead), so the evidence died with the teardown; its
canned "IMAGE BUILD / SPAWN INFRA" verdict was also wrong for the
containers-started-then-hung shape (the diagnose skill's signature catalog has the
correct triage). Fix the capture path to write unconditionally before teardown, and
teach the verdict the healthy-container-timeout branch.

## 9. Promote push-race handling

Two all-gates-green promotes lost the atomic-push race to a concurrent session's
promote in one evening (25-minute gate window; loser re-runs the full gate). Options,
either sufficient: a fetch-recheck-remerge retry loop inside `promote-to-main.sh`
before declaring the push lost, or a lightweight promote-lock convention between
concurrent sessions (tonight's manual fix — a cross-session hold request — worked but
does not scale). Also from the same evening: `TAP_TEST_JOBS` exists as the xdist
memory-pressure valve; promote invocations on a busy host should use it
(`TAP_TEST_JOBS=4`).

## Tracked elsewhere (deliberately not here)

- `artifact_manifest.json` per-install override — adopter/product engineering, not CI:
  samsite plugin README (Known Limitation) + rehome spec Status Details.
- The dead-PAT `/provision-secrets` end-to-end — secrets-mechanism validation, runs
  from any fresh `spawn --from …tap-plugin-samsite@v0.2.0#samsite`:
  `secrets-conditional-validation` memory + `spec-tap-boot-observability.md`.
