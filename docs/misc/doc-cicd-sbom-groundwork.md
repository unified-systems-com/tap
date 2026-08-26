---
spec: ../../specs/spec-cicd-sbom.md
audience: [llm, developer]
covers:
  - ../../specs/spec-cicd-sbom.md
  - ../../specs/spec-cicd-hardening.md
assumes:
  - Reader knows the publish pipeline shape (publish-images.yml + publish-release-tags.yml, req-cicd-build-once-artifact) and the digest-threading law (req-cicd-supply-chain-provenance-1).
---

# SBOM Groundwork — Findings, Prior Art, and Decisions

Spec: [spec-cicd-sbom.md](../../specs/spec-cicd-sbom.md)

The empirical and research record behind [spec-cicd-sbom.md](../../specs/spec-cicd-sbom.md),
gathered 2026-08-18 → 2026-08-20 during the v0.1.2 publish-gap incident and its follow-up.
Everything in the spec's requirements traces to a finding or a precedent recorded here.

## 1. The incident context that motivated this

The chain (full detail in spec-cicd-hardening's req-cicd-product-releases-1 and
req-cicd-supply-chain-provenance-1 notes):

1. **v0.1.2 publish gap** — publish-images' newest-main-wins cancellation killed the
   release commit's build 13s after merge; `:sha-153f6d7` never existed; the version-tag
   promotion starved; nobody noticed for 4 days because compose's `build:` fallback
   silently substituted from-source rebuilds. Fixes: isolated concurrency for release
   builds + `ref` backfill (PR #75), pull-only base compose (PR #76), CI rides `:latest`
   (PR #78).
2. **Digest threading** (PR #77) — the staging-tag hops between build and manifest jobs
   were TOCTOU windows where a `packages:write` holder could swap content and the
   attestation would then SIGN the tampered bytes. Now: push-by-digest, digests ride
   workflow artifacts, merge consumes `ref@digest`, fail-closed children-equality check
   before attesting. `provenance: false` on build legs is LOAD-BEARING (bare manifests
   make strict equality checkable; the provenance lane is GitHub attestations).
3. **The reproducibility discussion** that surfaced the SBOM need — see §2.

## 2. Reproducibility: what floats, what pins

Layer-by-layer truth for both images (established 2026-08-19):

| Layer | Pinned? | Mechanism |
| --- | --- | --- |
| Base image (wolfi-base) | yes | tag@digest in both Dockerfiles; Renovate bumps |
| OS packages (`apk add`) | **floats** | resolves Chainguard's CURRENT index at build time — both images |
| OpenSSL FIPS provider | yes (exactly) | version-pinned source URL; 3.0.9 is the CMVP #4282 artifact |
| Python closure (web) | yes | uv.lock, hash-verified, installed at runtime by `uv sync` |

Consequences:

* **A version's images = that commit's source × the build day's packages.** Rebuilding is
  not reproducible; the published artifact is the only pin. Live proof: the 0.1.2
  backfill built the 08-12 release commit on 08-19 — same source, that day's packages.
* **apk version-pinning is not a fix**: Wolfi is rolling; Chainguard drops old package
  versions from the index (their CVE model — the fix for a vulnerable package is that it
  ceases to exist). Pinning trades silent float for constant breakage with no
  rebuildability gained. Decision: option (a) — artifact-is-the-pin — is coherent, not
  merely cheap.
* **Chainguard's actual guarantees** (verified 2026-08-19): provenance/signatures/SBOMs
  for THEIR builds (melange/apko, Sigstore), minimal CVE surface, fast remediation.
  Consumer-side reproducibility is NOT offered — the rolling repo structurally opposes
  it; version retention is the paid product. Free-tier notes: Wolfi repo free;
  ~50 Starter images `:latest`-only; **Catalog Starter (2026-03): any team picks 5 free
  images from the full catalog** — back-pocket card for a maintained postgresql base
  (FIPS variants stay enterprise). No standing OSS-org grant program found.

So: release notes describe source changes; the OS-package delta between releases is
invisible without a build-time SBOM. That is the gap the spec closes.

## 3. Empirical findings: what scanners actually see in our images

Agent-verified 2026-08-20 against `tap-web:latest`, which on the scanning host resolved
to the immutable subject `ghcr.io/unified-systems-com/tap-web@sha256:be971fab5bb6f9b24be182b1b5cc9b51b62eea8458bd87247f59636ed74d53c2`
(record the digest, not the tag — the req-cicd-sbom-5 discipline, applied retroactively
to this doc's own evidence). Scanners: (syft v1.51.0 standalone;
buildkit-syft-scanner stable-1 embedding syft v1.42.3). The numbers below ARE the durable
record — the raw scan JSONs (~14MB) were ephemeral working artifacts, deliberately not
committed; re-derive them by re-running the scans described here against any published
image digest.

### 3.1 BuildKit `sbom: true` is a dead end for these images

* Syft's lockfile parser (`python-package-cataloger`) is a "declared/directory"
  cataloger — **excluded from image scans**. Full image scan: 1,229 artifacts, ZERO
  citing `/app/uv.lock`.
* `buildkit-syft-scanner` **hardcodes** installed-only cataloging: minimal-image tests
  (`COPY uv.lock`, `requirements.txt` control) → 0 packages; every cataloger-selection
  env override (`SYFT_SELECT_CATALOGERS`, `SYFT_CATALOGERS`, `SYFT_DEFAULT_CATALOGERS`)
  verified inert. Not configurable from build-push-action.
* The cataloger itself works when reachable: `dir:` scan of uv.lock → 69 packages
  (django 6.0.8 et al.).

### 3.2 What a default scan DOES emit — plausible garbage

* **~101 "installed" Python packages that are actually the wheel cache**: unpacked wheels
  under `/opt/uv-cache-seed/**` carry dist-info, so they masquerade as installed.
  vs the lock: 31 phantoms (maturin; setuptools ×2 versions; wheel ×3; setuptools'
  vendored jaraco-*/autocommand/inflect; a literal `my-test-package 1.0` test fixture)
  and 3 real members MISSING (colorama, tzdata, and **`tap` itself**).
* **1,012 Rust-crate entries** from cargo-auditable metadata inside `/usr/bin/uv` and
  `/usr/bin/uvx` — the tool's own closure drowning the artifact's.
* The wheel-cache inventory is load-bearing on an accident: change the cache-seeding
  strategy and the Python inventory silently vanishes.
* Sanity: the apk (Wolfi) side catalogs cleanly — 100 packages.

### 3.3 fips.so is invisible

`/usr/lib/ossl-modules/fips.so` appears only as an uncataloged-file "unknown"; the apk
`openssl` package does not claim it (correct — we build it). In a production attestation
the most compliance-significant binary in the image would appear nowhere. Hence
req-cicd-sbom-3 (hand-authored supplemental entries) — no scanner will ever fix this.

### 3.4 Cache trust chain (analysis, 2026-08-20 review)

Where the wheel-cache seed's integrity actually comes from, layer by layer — the analysis
that produced `req-cicd-supply-chain-provenance-2` (spec-cicd-hardening.md):

* **Build-time — verified.** `deps-warm` runs `uv sync --frozen`; every sdist/wheel uv
  acquires is checked against the sha256 recorded in `uv.lock` (git-reviewed, gated).
  The FIPS source compiles happen inside the attested build; the seed ships as an
  immutable image layer under the digest + SLSA provenance + Trivy scan.
* **Build-time residuals (named at provenance-1, unchanged):** compile OUTPUT is not
  hash-checkable (source verified, emitted wheel covered only by runner trust) and the
  Docker layer cache could poison `deps-warm` before any digest exists.
* **Boot-time — the gap provenance-2 closes.** The entrypoint's seed copy was a bare
  `cp` with no verification, and warm-cache `uv sync` does NOT re-verify hashes on
  cache hits (lock hashes verify at acquisition, not reuse). "First boot runs the
  attested bytes" was implied by image immutability, never verified at use. The fix is
  a build-time hash manifest of the seed + fail-closed entrypoint verification before
  seeding (TAP-ABORT on mismatch).
* **Tightened on review (Codex 2026-08-20, accepted in full):** verification is a full
  bidirectional reconciliation (mismatch + missing + EXTRA files — a padded seed must
  not pass); manifest keys on relative paths and excludes itself (generated under
  `/root/.cache/uv`, verified under `/opt/uv-cache-seed`); absent seed MAY degrade,
  present-but-invalid MUST abort (the entrypoint's "degrades cleanly" comment splits
  accordingly); verifier is stdlib-only Python (pre-venv, BusyBox-proof); result is
  machine-legible boot evidence, with an early pre-boot scratch record satisfying the
  before-tap.preboot timing.
* **Deliberately NOT closed:** the uv-cache VOLUME after seeding is host-trust domain —
  an attacker who can write a Docker volume can equally patch the venv or the running
  process, so re-verification there adds no security boundary. Cache misses fall back
  to PyPI with lock-hash verification, so the degraded path stays verified.

### 3.5 Implementation smoke findings (2026-08-20, pre-CI)

Built and proven live against `tap-web@sha256:78836f3d…` (arm64): 173 components =
100 apk + 69 pypi (the exact uv.lock closure — `+python-package-cataloger` DOES fire
on image scans when explicitly selected, confirming the -1 design) + 3 declared
out-of-band + `tap` itself at the built version; 123 dependency edges; both formats
schema-validate; phantom canaries absent. One trap caught by our own gate before CI
ever ran: syft's CycloneDX serialization emits every file as a name-only component
(~13.8k entries) unless `SYFT_FILE_METADATA_SELECTION=none` — a file inventory
masquerading as package claims, and the minimum-elements check correctly refused it.
The fix lives at the derivation, not the checks. Second trap, caught by the PR #86 lean-boot gate: the compose dev stack runs the ENTRYPOINT from the bind-mounted tree while the image lags — so new-verifier-plus-legacy-image (seed, no manifest) is a normal designed state, and the original abort-on-absent-manifest semantics bricked it. Amended three-way: valid → seed; invalid manifest → abort; NO manifest → never seed unverified bytes, warn, degrade to the lock-hash-verified slow path (manifest-stripping is not a distinct attack — whoever could strip it could modify the seed).

### 3.6 Plugin lane pilot findings (2026-08-20)

Built and proven on the production path: aws-core v0.4.2 (a real CI-only patch release)
→ tag push → thin caller → reusable lane → wheel provenance + both SBOM predicates
verified on the downloaded wheel. Traps banked: (a) syft `file:` does NOT unpack
archives — a raw .whl scan yields ZERO components; extract and dir-scan (the unpacked
dist-info is the cache-phantom mechanism used deliberately); (b) the file-metadata
flood repeats on dir scans — `SYFT_FILE_METADATA_SELECTION=none` everywhere;
(c) `actions/attest` `sbom-path` does not expand globs (`subject-path` does) — concrete
paths via step outputs; (d) `workflow_dispatch` runs the workflow file FROM THE
REQUESTED REF — dispatch at a pre-caller tag 422s, and hatch-vcs makes any non-tag ref
build a `.dev` version the identity gate correctly rejects, so retroactive attestation
of old tags is structurally closed: attestations flow forward from the first
caller-carrying tag.

## 4. Prior art — the five patterns in the wild

1. **Generate-and-attest, GitHub-native** (anchore/sbom-action → actions/attest-sbom):
   GitHub's documented flow; Syft generates, GitHub Sigstore-signs into the attestation
   store, `gh attestation verify` verifies. De-facto default for GitHub-hosted OSS.
2. **BuildKit in-registry attestations** (`sbom: true`): Docker's pattern; per-arch SBOMs
   as `unknown/unknown` index entries. Field lessons: attestations do NOT survive naive
   manifest merges, and content assumes conventional installed layouts (§3 rules it out
   for us).
3. **Signed registry attestations via cosign** (`cosign attest`): Chainguard's pattern
   (apko emits exact SBOMs, cosign signs them as OCI referrers). Key data point:
   **`cosign attach sbom` was deprecated 2024** because unsigned SBOMs are unverifiable —
   the ecosystem converged on signed-or-nothing, independently validating TAP's
   TOCTOU/signing posture.
4. **Purpose-built first-party generator** (kubernetes-sigs/bom): k8s wrote its own SPDX
   tool because generic scanners missed project reality. Transferable lesson: mature
   projects CURATE and AUGMENT generation rather than trusting a default scan — the
   k8s-scale response (own tool) is overkill for TAP; the posture is not.
5. **Multi-arch consensus** (Chainguard's "SBOMs in a multi-architecture world"): each
   platform variant carries its own standalone SBOM (consumers pull arch images
   directly); no standard merged index-level SBOM exists.

Format sidebar: CycloneDX (OWASP) owns security tooling — Dependency-Track, VEX triage,
Trivy/Grype native, the safer EU-CRA bet; SPDX (Linux Foundation) owns license/legal and
government adoption (k8s ships it). Both satisfy CISA 2026 minimum elements. Syft emits
both from one scan → format is a serialization choice, not lock-in (req-cicd-sbom-6).

## 5. Decisions and their reasoning (the trail to each requirement)

| Decision | Reasoning | Req |
| --- | --- | --- |
| Standalone pinned Syft, buildx `sbom:true` forbidden | §3.1: hardcoded catalogers make the one-liner emit wrong content, unconfigurably | sbom-1 |
| Lockfile closure in, cache/binary noise out | §3.2: uv.lock IS what runs (hash-verified `uv sync`); cache inventory ≈ closure but wrong both directions | sbom-2 |
| Hand-authored out-of-band entries | §3.3; crypto-BOM discipline gets its first standard-format artifact | sbom-3 |
| GitHub attest-sbom home; digest subjects; no mutable-name hops | Matches existing provenance lane (one verify story, zero new trust roots); digest-threading law extends; TOCTOU analysis: a signature binds identity to bytes, not bytes to origin — an unsigned mutable hop lets the signer launder a tamper | sbom-4 |
| Per-arch standalone, no index merge | Pattern 5 consensus + our verified per-arch digests are the natural subjects | sbom-5 |
| CycloneDX primary + SPDX emitted day one, same scan | Claude review 2026-08-20 [P2] accepted: Syft serializes both from one derivation, so deferring SPDX bought nothing — SPDX carries government/legal gravity (BuildKit-native, k8s bom); derive-once holds (two independent scans WILL drift); both attested, both schema-validated, minimum-elements battery on the primary | sbom-6 |
| Per-arch verify path written, not implied | Claude review 2026-08-20 [P2]: tag → platform digest (imagetools inspect + jq select) → gh attestation verify with EXPLICIT --predicate-type (default is SLSA provenance; SBOM predicates are cyclonedx.org/bom and spdx.dev/Document) — canonical flow in the spec, verbatim in release docs | sbom-5 |
| Fail-closed canary guard | Every observed failure mode was silent plausibility; convert quiet wrongness into a red publish | sbom-7 |
| Release diffs deferred | Pure consumer of the rest; the customer upgrade-diff promise, machine-checkable | sbom-8 |
| uv/uvx are declared components, not noise | Claude review 2026-08-20 [P1]: the crate-metadata exclusion must not swallow the executables — uv/uvx arrive via digest-pinned COPY --from (Dockerfile), i.e. out-of-band by sbom-3's own rule; declared entries with version/source-digest/path/sha256/license/purl, canary-guarded | sbom-2/-3/-7 |
| Supplemental entries = one schema'd manifest | Claude review 2026-08-20 [P2]: hand-authored entries must be a single structured supplemental-manifest format with committed JSON Schema + loader validation (the house JSON-lane rule), merged during the single derivation (never post-hoc on an attested doc), canary-proven in the output and -12-reconciled against the Dockerfiles | sbom-3 |
| Conformance validation beside canaries | Codex review 2026-08-20 [P1]: canaries catch TAP-specific lies but not malformed valid-looking documents — schema-validate CycloneDX + CISA/NSA 2026 minimum-elements fields (identifiers, hashes, dependency graph, tool/context, coverage statement); signature satisfied at the attestation layer, mapping stated not pretended | sbom-11 |
| Declaration detected, never remembered | George 2026-08-20 (review): sbom-3 alone is opt-in and forgettable — derive the out-of-band inventory deterministically (Dockerfile COPY --from enumeration + image-level unknowns budget, the crypto-BOM fail-closed discipline generalized; python source-built set derives from no-binary config) and reconcile against declarations both directions | sbom-12 |
| Ecosystem coverage generalized | George 2026-08-20 (review): vendored JS (tabulator/echarts + peers) is ALREADY in the artifact with no manifest — versions in spec prose, invisible to scanners AND to the unknowns budget (minified JS isn't executable-format); named gap needing a vendored-assets manifest; first-party Rust inverts the uv story (cargo-auditable IS the manifest); TS rides npm locks; new ecosystems trip -12 on arrival | sbom-13 |
| Adopt native distribution, never roll our own | George 2026-08-20 (three-step reconsideration, recorded as arrived at): (1) Chromium README.chromium-style vendored-JS manifest proposed from prior art; (2) challenged — "is there really no npm standard?" — pivoted to package-lock as the manifest (native Renovate/Dependabot/Syft replace three hand-built integrations); (3) challenged again — "we have a build system, why vendor at all?" — pivoted to build-time acquisition converging JS onto the Python model; (4) challenged a third time — "isn't curl-from-lock rolling our own npm fetch?" — YES: a lock-parsing fetcher is a bespoke npm client (npm versions the lock format; no standalone no-node fetch standard exists outside Bazel/Nix), so acquisition is `npm ci --ignore-scripts` in a digest-pinned builder stage — the same boundary as ossl-builder/deps-warm; toolchain avoidance applies to runtime + dev loop, not to hermetic build stages. Elevated to doctrine in -13: every ecosystem rides its own registry+lockfile, merged at the lockfile seam; hand-authored manifests = last-resort named debt (the C/C++ niche Chromium's pattern was built for). The lesson for the record: prior art must be matched to the ECOSYSTEM SHAPE it came from — Chromium's pattern is best-in-class for registry-less ecosystems and over-engineering for registry-backed ones | sbom-13 |
| Plugin-declared SBOMs | George 2026-08-20 (review): declare-vs-decide (the manifest [fips] precedent) — plugin release CI declares an attested SBOM keyed (name, version) = the boot-record key; system verifies + composes; flavored images derive ONCE from the bake-time combined lock, with a declared-vs-derived reconciliation as a canary red; trust inherits req-tap-plugin-extdev-signing when it lands | sbom-10 |
| Extensible to ready-made appliance images | George 2026-08-20: profile-baked plugin images are on the roadmap; the artifact/runtime boundary (not core/plugin) is the durable line — baked plugin closures enter the image SBOM via the same declared-manifest principle (boot-record data as the manifest); parameterize generation + canaries per flavor now, cheap at design time / expensive to retrofit | sbom-9 |

Layered-BOM model (scope boundary, refined 2026-08-20): the durable line is
BAKED-IN-ARTIFACT vs ADDED-AT-RUNTIME, not core-vs-plugin. The image SBOM is the
ARTIFACT-level inventory (universal — every copy of a version, everywhere; for a flavored
ready-made image that includes its baked plugin closure); the boot record is the
INSTANCE-level BOM (particular — what this running instance actually loaded; for a
ready-made instance, ideally a digest-reference to the image SBOM plus runtime deltas
only). They compose; neither substitutes for the other.

## 6. Named residuals (declared, not solved here)

* **Build-cache poisoning** — buildcache tags are mutable; a forged cache entry injects
  content BEFORE the first digest exists, upstream of SBOM and provenance alike.
  Accepted at req-cicd-supply-chain-provenance-1; blast radius = our own
  `packages:write` surface.
* **Compromised runner** — tampered bytes at birth; no downstream digest/signature
  discipline helps. Addressed by pinned actions, least-privilege tokens, provenance.
* **Wheel-cache seed at boot** — WAS a residual (bare `cp`, no verification at use);
  now specced as `req-cicd-supply-chain-provenance-2` (see §3.4). The post-seed VOLUME
  stays a named host-trust residual.
* **db-Dockerfile PR coverage** — a PR editing docker/postgres/Dockerfile is not
  exercised by CI (db image never built from the PR tree). Pre-existing, named at PR #78.
* **Registry-side SBOM copy** for mirrored/air-gapped consumers — deferred; signed-only
  if ever (Pattern 3's deprecation lesson).

## 7. Sources

* anchore/sbom-action: https://github.com/anchore/sbom-action
* GitHub artifact attestations: https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
* kubernetes-sigs/bom: https://github.com/kubernetes-sigs/bom
* cosign attach-sbom deprecation: https://github.com/sigstore/cosign/issues/2755
* cosign SBOM spec: https://github.com/sigstore/cosign/blob/main/specs/SBOM_SPEC.md
* Chainguard, "SBOMs in a multi-architecture world": https://www.chainguard.dev/unchained/sboms-in-a-multi-architecture-world
* Chainguard SBOM/attestation distinction: https://edu.chainguard.dev/open-source/sbom/sboms-and-attestations/
* CycloneDX vs SPDX (2026 landscape): https://www.interlynk.io/resources/cyclonedx-vs-spdx-sbom-format
* CISA minimum-elements mapping: https://runsafesecurity.com/blog/sbom-minimum-elements-cyclonedx-spdx/
* BuildKit attestation storage (unknown/unknown platform entries): https://github.com/goharbor/harbor/issues/22848
