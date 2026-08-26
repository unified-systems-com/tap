---
spec: ../../tap_plugins/specs/spec-tap-plugin-architecture.md
audience: [llm, developer]
covers:
  - ../../tap_plugins/specs/spec-tap-plugin-architecture.md
  - ../../specs/spec-cicd-hardening.md
  - ../../specs/spec-cicd-sbom.md
assumes:
  - Reader knows the plugin identity lockstep (slug == entry-point key == tap_plugin.<slug> == dist, doc-plugin-slug-load-bearing.md) and the reusable release lane (plugin-release-sbom.yml, req-cicd-sbom-10 / req-cicd-release-artifacts).
---

# Plugin Identity Fork Plan — Product-Line Naming, the Fork Wave, and the PyPI Strategy

**Status: DRAFT — blocked on one decision (the ownership table, §3). Everything else
is settled design from the 2026-08-22/23 naming discussions and is ready to run once
that table is blessed. This plan feeds the broader strategy rewrite (rampart-strategy.com
arc); execute it after tap PR #103 lands and the `aws-secrets-source-v0.2.0` release
verifies.**

## 1. Decisions already made (the settled design)

1. **Product-line naming.** Plugin distributions are named `<line>-plugin-<name>`
   (e.g. `rampart-plugin-aws-core`, `git-serious-plugin-github-core`). The line prefix
   states *ownership* (which product line is responsible for the capability), not the
   host — plugins remain TAP plugins usable across lines. The `-plugin-` infix is kept
   deliberately: unlike `pytest-*` (where the prefix IS the host and implies
   plugin-ness), a line prefix will also front non-plugin artifacts (CLIs, tooling), so
   the token is the cross-line "this is a plugin" marker — for humans and cheap
   tooling (`grep -- -plugin-`), never for trust.
2. **One rule, no grandfather clauses.** Dist `<line>-plugin-<name>` ↔ slug
   `<line>_<name>` ↔ import `tap_plugin.<line>_<name>`. This applies to EVERY plugin,
   including the neutral substrate (`tap` is the commons line: `tap-plugin-compliance-core`
   / slug `tap_compliance_core`). A half-tidy version that grandfathers bare slugs
   recreates the seam this wave exists to remove.
3. **Fork, never rename-in-place.** Slug renames under live data are forbidden
   (uuid5/collector-identity fallout — twice bitten). The mechanism is an **identity
   fork**: new repo, new slug, new namespace dir, new dist; the old repo freezes. No
   instance data migrates; fresh identities collect fresh. This is cheap precisely
   because consumer count is one (samsite, pinned) — the price grows with every
   consumer, so the wave runs early or never.
4. **Trust stays functional; names are labels.** Identity = valid `tap-plugin.toml` +
   `tap.plugins` entry point; authorization = boot profile; provenance = attestations.
   The name-shape rules below are *coherence checks*, not trust derivations (the
   2026-08-22 decoupling decision stands). With the manifest declaring its `line`, the
   slug↔dist bijection becomes mechanically checkable again — restoring, as an explicit
   gate, the structural collision-immunity the old derivation gave by accident.
5. **Collision defense in three layers.** (a) Boot-time fail-closed gate: duplicate
   `tap.plugins` entry-point keys or duplicate profile slugs → `PrebootError` naming
   both dists (needed for third-party plugins regardless of this wave); (b) the
   `<line>_` slug convention makes collisions unlikely by construction; (c) the slug
   register (doc-plugin-slug-load-bearing.md) is the org-wide first-come ledger —
   claiming a slug = a row, at review time.
6. **Scale posture on external collisions.** Existing claimants of the "rampart" name
   (Microsoft AI Red Team's pytest framework on PyPI since 2026-05; the rampart.dev JS
   platform) are non-competing at our scale and trajectory; the brand anchor is
   **rampart-strategy.com**. Not worrying ≠ not claiming: anchor names get claimed the
   day a line is blessed (§5).

## 2. Sequencing (what runs before this wave)

Already in flight, independent of the ownership decision:

- **PR #103** (release-artifact conventions + generalized release lane) — awaiting
  code-owner approval; then tap-build-dependencies PR #1 merges and
  `aws-secrets-source-v0.2.0` tags and verifies. Untouched by this plan (it is not a
  plugin; its name stays).
- **Decoupling wave** (from the 2026-08-22 reliance survey — wanted regardless):
  1. Fail-loud fix for the two silent-skip gates: `tap/preboot.py:582`
     (`requires_tap` floor) and `:665` (dependency min-version) `continue` when the
     dist lookup misses — convert to `PrebootError` (or share one resolution with the
     conformance gate at `:534` so they cannot disagree).
  2. Replace the release lane's `tap-plugin-*` prefix reservation with the functional
     check: a wheel advertising a `tap.plugins` entry point must ride the plugin arm.
  3. Manifest/profile-declared `dist` (+ `line`), `dist_name_for_slug` becomes a
     lookup with convention fallback; conformance gate checks declared == installed.
  4. Nightly fleet discovery moves off the org-roster `tap-plugin-*` prefix scan to
     the boot-profile roster (closes the live contradiction with
     req-tap-plugin-arch-identity-4).

## 3. THE OPEN DECISION — ownership table

George assigns each existing plugin to a line. Proposed starting point (UNCONFIRMED —
the strategy rewrite owns this):

| Current slug | Proposed line | New dist | New slug |
| --- | --- | --- | --- |
| aws_core | rampart | rampart-plugin-aws-core | rampart_aws_core |
| fedramp_20x_ksi | rampart | rampart-plugin-fedramp-20x-ksi | rampart_fedramp_20x_ksi |
| sigstore_core | rampart | rampart-plugin-sigstore-core | rampart_sigstore_core |
| github_core | git-serious | git-serious-plugin-github-core | git_serious_github_core |
| compliance_core | tap (commons) | tap-plugin-compliance-core | tap_compliance_core |
| identity_core | tap (commons) | tap-plugin-identity-core | tap_identity_core |
| computing_core | tap (commons) | tap-plugin-computing-core | tap_computing_core |
| grid_fixtures | tap (commons) | tap-plugin-grid-fixtures | tap_grid_fixtures |
| gryphon_playground | tap (commons) | tap-plugin-gryphon-playground | tap_gryphon_playground |
| administrivia | tap (commons)? | tap-plugin-administrivia | tap_administrivia |
| roscale | ? | ? | ? |
| samsite | ? (Sam's arc) | ? | ? |

Also to bless: the registered-prefix set itself (`tap`, `rampart`, `git-serious`, …) —
a one-file registry; adding a prefix = a reviewed spec row + the claiming ceremony (§5).

## 4. The fork wave — execution checklist

Per plugin (scriptable; run per line as each line becomes real, or as one wave):

1. Fork the repo to the new name (history preserved); archive the old repo with a
   README pointer. GitHub redirects cover old clones/URLs.
2. In the fork: rename `tap_plugin/<old_slug>/` → `tap_plugin/<new_slug>/`; update
   manifest slug (+ new `line`/`dist` fields), entry-point key, pyproject `name`,
   in-repo boot records, tests' `--pyargs` paths, thin-caller `plugin_slug`, README.
3. Gate: `validate_plugin --strict` + `pytest --pyargs tap_plugin.<new_slug>` (the
   evicted-plugin lesson: "it boots" proves nothing).
4. Release under the new identity (bare `vX.Y.Z` tags — single-artifact repos);
   attestations + SBOMs ride the existing lane unchanged.
5. Slug register: add the new row, mark the old slug RETIRED-NEVER-REUSE.

Core repo, once:

6. Boot profiles (`boot/*.boot.json`): new dists/slugs/URLs.
7. Core-app tests that hardcode plugin slugs (the known focused-session gap) — sweep
   and update.
8. Nightly roster, docs, CLAUDE.md examples, spec examples.
9. Naming spec section: canonize the grammar, the prefix registry, the slug-issuance
   rule ("slugs are immutable identity; conventions govern issuance, never
   retrofits"), and the multi-registry name-claiming ritual.

Consumers:

10. Dev instances: respawn (disposable by design).
11. **Sam/samsite**: keeps running pinned artifacts from the frozen repos — zero
    breakage today. Their move to the new identities is a planned migration (with a
    collector-identity/data mapping) whenever the actual refactor is scheduled.
    **Update the samsite addendum (the customer-promise contract) when this wave
    executes** — frozen-repo status and the upgrade path are exactly what it records.

## 5. PyPI / uv publishing strategy (runs AFTER the rename — names are forever)

The machinery is ~90% built (wheels at immutable tags, identity gate, SBOMs,
provenance, OIDC CI). The delta:

1. **Order of operations is the whole strategy**: ownership table → fork wave → THEN
   first publish. The first upload of each name freezes it permanently; publishing
   pre-rename would claim the wrong names.
2. **Claiming ceremony (per line, the day it's blessed)**: check availability
   (`https://pypi.org/pypi/<name>/json` → 404 = free) across PyPI + npm + the domain +
   GitHub org — a name is a portfolio of claims, not one claim (the rampart lesson:
   PyPI taken by Microsoft 2026-05, .dev taken by a JS platform, three months was all
   it took). Claim the line's anchor name + first dists via **PyPI pending
   publishers** (Trusted Publishing config that claims the name on first CI publish —
   no API token ever exists).
3. **Trusted Publishing only.** Per-project OIDC binding (repo + workflow file [+
   environment]); 2FA on the account. No tokens, matching the org's no-secrets CI
   posture. PEP 740 attestations come free: the publish action generates
   Sigstore-backed provenance PyPI displays — a second, index-native home for the
   existing provenance story.
4. **The publish step is ~10 lines in the reusable lane** (`uv publish` or
   pypa/gh-action-pypi-publish), placed AFTER the existing identity/SBOM/attestation
   gates so nothing reaches the index that didn't pass everything. One change, all
   repos inherit via thin callers. Decide wheel-only vs wheel+sdist (index convention
   wants both; one flag).
5. **History**: publish from the first post-rename release forward; no backfill of old
   tags (fights the retroactive-attestation wall, and the old names are being
   retired anyway).
6. **Consumer switch is a separate, later wave**: boot profiles move from authed
   git-source pins to index requirements (uv.lock gains registry hashes); the bespoke
   git-source install path (`plugin_source_auth`) retires for public plugins. PyPI
   publishing itself is additive — nothing forces the switch.
7. **De-risk option**: one TestPyPI dry-run of a single plugin exercises the whole
   flow without claiming anything real.
8. **README bonus**: swap the static Python-version badge for the dynamic
   `pypi/pyversions` form once packages are live.

## 6. What this plan deliberately does not do

- No slug renames-in-place, ever (the standing rule this plan writes into the spec).
- No trust from names — the prefix registry and shape checks are coherence and
  issuance governance only.
- No forced consumer migration: Sam's timeline is Sam's; the frozen repos hold.
- No PyPI backfill of pre-rename releases.
