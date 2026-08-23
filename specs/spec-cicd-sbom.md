# SBOM Emission Specification

## Philosophy

An SBOM (software bill of materials) is the machine-readable answer to "what exactly is
inside this artifact?" — per-component, per-version, diffable, consumable by scanners and
by Player-3 tooling without pulling the image apart. TAP's publish pipeline already proves
*who* built an artifact and *from which commit* (SLSA provenance,
`req-cicd-supply-chain-provenance`); the SBOM is the missing *what*.

Three facts, all established empirically (see
[doc-cicd-sbom-groundwork](../docs/misc/doc-cicd-sbom-groundwork.md)), shape every
requirement below:

1. **The published artifact is the version pin.** The OS package layer floats against
   rolling Wolfi at build time (`req-cicd-product-releases-3` groundwork): a version's
   images are that commit's source × the build day's packages, and a rebuild is not
   reproducible. Only an SBOM captured at build time records which packages a release
   actually shipped — release notes describe source changes; the package delta rides
   silently without it.
2. **The obvious one-liner produces a wrong SBOM for our images.** BuildKit's `sbom: true`
   runs a scanner locked to installed-package cataloging. Our web image deliberately
   contains no installed Python environment (wheel-cache + runtime `uv sync`), so the
   default scan misses the real closure (`uv.lock` is never parsed), inventories the wheel
   cache as ~101 phantom "installed" packages (missing `tap` itself; including build
   backends at multiple versions and a literal `my-test-package` test fixture), and drowns
   the result in ~1,012 Rust-crate entries from the `uv` binary. A plausible-but-wrong
   SBOM is worse than none: consumers diffing releases would chase ghosts.
3. **No scanner can see a hand-built component.** The single most compliance-significant
   binary in the image — the self-built OpenSSL 3.0.9 FIPS provider (`fips.so`, CMVP
   #4282) — appears in no package database and therefore in no scanned inventory. Honest
   SBOMs for TAP require deliberate augmentation, not just scanning.

The prior-art consensus (Kubernetes `bom`, Chainguard/apko, the cosign `attach sbom`
deprecation, GitHub's generate-and-attest flow) reduces to: **curate the generation, sign
the result, keep per-arch SBOMs standalone** — and TAP's digest-threading law
(`req-cicd-supply-chain-provenance-1`) extends unchanged: no mutable-name hop between
generation and signature.

Scope: the published `tap-web` and `tap-db` images today, extensible to **flavored
ready-made images** tomorrow (req-cicd-sbom-9). The durable boundary is NOT "core vs
plugins" — it is **baked-into-the-artifact vs added-at-runtime**: the image SBOM is the
*artifact-level* BOM (what every copy of this version contains everywhere); the boot
record is the *instance-level* BOM (what this running instance actually loaded). A
ready-made image that bakes a boot profile's plugin set moves that plugin closure across
the boundary — into the artifact, and therefore into its SBOM. Runtime-added plugins
remain the boot record's territory. The two compose; neither substitutes for the other.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Honest | The SBOM lists what the artifact actually carries — the true locked closure, no phantoms, hand-built components included |
| 2. | Signed | SBOMs travel only as signed attestations bound to content digests; an unsigned SBOM is a rumor |
| 3. | Diffable | SBOM(vN) − SBOM(vN−1) is the mechanical answer to "what changed under the version bump" — the upgrade-diff promise made machine-checkable |
| 4. | Guarded | A regression to a wrong-but-plausible SBOM fails the publish, loudly — accuracy is load-bearing, never accidental |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-cicd-sbom-1 | [Curated Standalone Generation](#curated-standalone-generation) | Implemented | Pinned standalone Syft against verified per-arch digests; BuildKit `sbom: true` is FORBIDDEN for these images |
| req-cicd-sbom-2 | [Closure Accuracy](#closure-accuracy) | Implemented | Locked Python closure IN (uv.lock cataloger); wheel-cache + uv-binary phantoms OUT (path excludes) |
| req-cicd-sbom-3 | [Out-of-Band Components Declared](#out-of-band-components-declared) | Implemented | Anything entering the image outside a package manager gets a hand-authored entry — first: `fips.so` (OpenSSL 3.0.9, CMVP #4282) |
| req-cicd-sbom-4 | [Signed Digest-Bound Home](#signed-digest-bound-home) | Implemented | `actions/attest` (sbom-path) per arch digest, GitHub attestation store; digest-threading law applies end to end; registry copy (if ever) must be a signed attestation, never an attachment |
| req-cicd-sbom-5 | [Per-Arch Standalone SBOMs](#per-arch-standalone-sboms) | Implemented | One SBOM per platform digest; no merged index-level SBOM exists |
| req-cicd-sbom-6 | [Single Derivation, Format as Serialization](#single-derivation-format-as-serialization) | Implemented | One Syft scan per digest is canonical; CycloneDX JSON + SPDX JSON BOTH emitted from that same scan on day one; CycloneDX primary |
| req-cicd-sbom-7 | [Canary Guard](#canary-guard) | Implemented | Fail-closed publish check: expected components present, known phantoms absent — else no attestation |
| req-cicd-sbom-8 | [Release SBOM Diffs](#release-sbom-diffs) | Backlog | Human-readable package delta per release, feeding the customer upgrade-diff contract; consumer of 1–7, not a blocker |
| req-cicd-sbom-9 | [Flavored Ready-Made Images](#flavored-ready-made-images) | Proposed | Design constraint now, implementation with the appliance-image work: an image baking a boot profile's plugins ships an SBOM covering core + baked plugin closure, from the same declared-manifest principle |
| req-cicd-sbom-10 | [Plugin-Declared SBOMs](#plugin-declared-sboms) | Implemented | Declare-vs-decide: plugin release CI declares an attested per-release SBOM; the system verifies and composes, never re-derives blindly; bake-time combined lock is the single derivation for flavored images |
| req-cicd-sbom-11 | [Standards Conformance Validation](#standards-conformance-validation) | Implemented | Schema-validate the CycloneDX document + fail-closed minimum-elements field checks (CISA/NSA 2026); canaries catch TAP-specific lies, this catches malformed valid-looking SBOMs |
| req-cicd-sbom-12 | [Out-of-Band Detection Gate](#out-of-band-detection-gate) | Proposed | Declaration is DETECTED, never remembered: Dockerfile-derived out-of-band inventory + image-level unknowns budget both reconcile against declarations, fail-closed |
| req-cicd-sbom-13 | [Ecosystem Coverage](#ecosystem-coverage) | Proposed | Doctrine: adopt each ecosystem's OWN distribution system (registry + lockfile + integrity) and merge at the lockfile seam — never roll our own; hand-authored manifests are last-resort named debt; vendored JS is the named gap and first test |
| req-cicd-sbom-14 | [Consumer Verification Docs](#consumer-verification-docs) | Proposed | The req-cicd-sbom-5 resolve-and-verify flow carried verbatim in the release/consumer documentation, once that surface exists |
| req-cicd-sbom-15 | [Plugin SBOM Composition](#plugin-sbom-composition) | Proposed | The composition half of -10: bake-time single derivation reconciled against plugin-declared SBOMs; boot records reference release SBOMs by digest — rides the appliance arc with -9 |

---

### Curated Standalone Generation
----
RID: `req-cicd-sbom-1`
Status: `Implemented`
Trace: `non-python` — scripts/sbom/generate.py

SBOMs for the published images MUST be generated by a **pinned standalone Syft**
invocation running as a publish-pipeline step, scanning each **verified per-arch digest**
(the digests the merge step verified under `req-cicd-supply-chain-provenance-1`).

BuildKit's built-in generator (`sbom: true` on the build step) is **FORBIDDEN** for these
images and MUST NOT be enabled: `buildkit-syft-scanner` hardcodes installed-only
catalogers (all cataloger-selection overrides verified inert), pins an older Syft, and —
against our venv-less image layout — emits the phantom inventory described in the
Philosophy. This is not a preference; enabling it would publish a wrong SBOM that no
downstream consumer could distinguish from a right one.

The Syft version is pinned and Renovate-managed like every other pipeline dependency;
bumps ride PRs, never floats.

### Closure Accuracy
----
RID: `req-cicd-sbom-2`
Status: `Implemented`
Trace: `non-python` — scripts/sbom/generate.py

The web image's SBOM MUST contain the **locked Python closure** — the packages `uv.lock`
resolves, which are byte-for-byte what runtime `uv sync` installs — sourced via Syft's
declared-package (lockfile) cataloger explicitly enabled for the scan.

The SBOM MUST NOT contain the wheel-cache or tool-binary phantom inventory. At minimum
the scan excludes `/opt/uv-cache-seed/**` (unpacked-wheel `dist-info` masquerading as
installed packages: build backends, vendored internals, multi-version duplicates, test
fixtures) and the ~1,012 Rust-crate entries of **embedded cargo-auditable metadata**
inside the `uv`/`uvx` binaries — the tool's own dependency closure, not the artifact's.
The exclusion is the embedded *metadata*, NEVER the executables themselves: `uv` and
`uvx` are real, load-bearing components of the image and MUST appear in the SBOM — as
declared out-of-band entries under req-cicd-sbom-3, since they arrive by digest-pinned
`COPY --from` rather than a package manager. Rationale for the cache exclusion: the
cache is *available bytes*, not *running software*; its inventory approximates the
closure while missing real members (`colorama`, `tzdata`, `tap` itself) and adding ~31
phantoms — and it vanishes entirely if the cache-seeding strategy changes. An SBOM must
never be load-bearing on an accident.

### Out-of-Band Components Declared
----
RID: `req-cicd-sbom-3`
Status: `Implemented`

Any component that enters a published image **outside a package manager** — compiled from
source in a build stage, copied from a builder, vendored by hand — MUST be declared in
the SBOM via a hand-authored supplemental entry, maintained alongside the Dockerfile that
introduces it.

First and motivating member: the self-built OpenSSL **3.0.9 FIPS provider**
(`/usr/lib/ossl-modules/fips.so`, CMVP certificate #4282) in both images. No scanner can
infer it (verified: it surfaces only as an uncataloged-file unknown), yet it is the most
compliance-significant binary TAP ships. Its SBOM entry is the first machine-readable
artifact of the crypto-BOM discipline (`req-fips-crypto-bom`, spec-fips.md): the crypto
provider inventory, in a standard format, per artifact.

Second members: the **`uv` and `uvx` executables** in the web image, copied by
digest-pinned `COPY --from` from the upstream `ghcr.io/astral-sh/uv` image — outside any
package manager, therefore declared. (Their ~1,012 embedded cargo-auditable crate entries
stay excluded under req-cicd-sbom-2; the executables do not.)

Each declared entry carries, at minimum: component name, **version**, **source** (for
copied binaries: the upstream image ref + digest; for self-built: the pinned source URL),
**file path in the image**, **SHA-256 of the file**, **license**, and a **purl/CPE where
one exists**.

The declarations are **one small structured supplemental-manifest format** — not prose,
not per-entry ad-hoc files: a single manifest per image, living alongside the Dockerfile
that introduces its components (so a digest-pin bump and its SBOM entry change in the
same diff), **validated against a committed JSON Schema at load** (the standing TAP rule
for structured formats: schema + loader validation + descriptions on the top level and
every entry, for AI and security readers), **merged into the generated CycloneDX during
the single derivation** (req-cicd-sbom-1/-6 — the merge is part of generation, never a
post-hoc edit to an attested document), and covered both ways: canaries (req-cicd-sbom-7)
prove the merged entries survived into the output; the detection gate (req-cicd-sbom-12)
proves the manifest matches what the Dockerfiles actually introduce. A schema-invalid
manifest fails the publish exactly like a failed canary.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-3-1 | Committed manifests validate | Implemented | Both images' committed supplemental manifests load and validate against the committed JSON Schema. | |
| req-cicd-sbom-3-2 | Schema failure is loud | Implemented | A manifest missing a required field fails the loader with a validation error, never a silent skip. | |
| req-cicd-sbom-3-3 | Injection carries the fields | Implemented | Injected components survive CycloneDX and SPDX schema validation carrying artifact-computed hashes, sources, and the coverage statement. | |

This requirement is the general rule; the guard for it is req-cicd-sbom-7's canary check
(a missing declared component fails the publish).

### Signed Digest-Bound Home
----
RID: `req-cicd-sbom-4`
Status: `Implemented`
Trace: `non-python` — .github/workflows/publish-images.yml

SBOMs are published as **signed attestations in the GitHub attestation store**
(`actions/attest` with `sbom-path` — the boring-current action; `actions/attest-sbom`
is deprecated in its favor), subject = the verified per-arch image digest — the same home,
identity root, and `gh attestation verify` story as the existing SLSA provenance. No new
trust roots.

The digest-threading law (`req-cicd-supply-chain-provenance-1`) extends to SBOMs: between
generation and signature the SBOM and its subject MUST never be referenced through a
mutable name. The scan targets `ref@digest`; the attestation subject is that same digest;
the document travels within one job (or via integrity-held workflow artifacts, never via
registry round-trip).

The registry-side copy landed WITH the GitHub home rather than as a deferral:
`actions/attest`'s `push-to-registry: true` pushes the identical Sigstore-signed
bundle to GHCR as an OCI referrer (matching the provenance step's existing behavior)
— the signed form, satisfying the mirrored/air-gapped consumer without any second
signing mechanism. An unsigned attachment remains forbidden: the ecosystem
deprecated `cosign attach sbom` for exactly the trust gap TAP's posture forbids.

### Per-Arch Standalone SBOMs
----
RID: `req-cicd-sbom-5`
Status: `Implemented`
Trace: `non-python` — .github/workflows/publish-images.yml

Each platform variant (amd64, arm64) carries its **own standalone SBOM**, attested
against its own digest. No merged index-level SBOM is produced. Rationale (prior-art
consensus): consumers can and do pull a platform manifest directly, so its SBOM must
stand alone; and the per-arch closures genuinely differ (compiled wheels, arch-specific
apk packages). The multi-arch answer is "ask for the platform you run," not a synthetic
union document.

A consumer starting from a version tag MUST have a written, exact resolve-and-verify
path — the two-step flow below is canonical. (Carrying it verbatim in the
release/consumer documentation is req-cicd-sbom-14 — a docs surface that does not
exist yet; a per-arch design without the written path just relocates the confusion.)

```bash
# 1. Resolve the version tag to YOUR platform's digest (the SBOM subject):
docker buildx imagetools inspect ghcr.io/unified-systems-com/tap-web:X.Y.Z \
  --format '{{json .Manifest}}' \
  | jq -r '.manifests[] | select(.platform.os=="linux" and .platform.architecture=="arm64") | .digest'

# 2. Verify the SBOM attestation FOR THAT DIGEST. The --predicate-type flag is
#    REQUIRED: `gh attestation verify` defaults to SLSA provenance and will not
#    find an SBOM attestation without it.
gh attestation verify oci://ghcr.io/unified-systems-com/tap-web@sha256:<digest> \
  --owner unified-systems-com \
  --predicate-type https://cyclonedx.org/bom          # primary (CycloneDX)
#   --predicate-type https://spdx.dev/Document/v2.3   # the SPDX serialization
# (Use the EXACT predicate URI the attestation was emitted with — for SPDX 2.3
#  that is the versioned https://spdx.dev/Document/v2.3, not the bare form.)
```

(The plain provenance verify, no `--predicate-type`, continues to work unchanged for
"who built this"; the SBOM predicate answers "what is inside it." Same digest, two
questions, two predicates.)

### Single Derivation, Format as Serialization
----
RID: `req-cicd-sbom-6`
Status: `Implemented`
Trace: `non-python` — scripts/sbom/generate.py

One Syft scan per digest is the **single derivation**; formats are serializations of it.
BOTH standard formats are emitted from that same scan, immediately: **CycloneDX JSON as
primary** (security-consumer gravity: Dependency-Track, VEX-aware triage, Trivy/Grype
native) and **SPDX JSON alongside it** (government/legal gravity; the format BuildKit
emits and Kubernetes' `bom` is built on — dull interoperability is the point of an
SBOM). Both ride the same signed attestation home (req-cicd-sbom-4) against the same
digest; both schema-validate under req-cicd-sbom-11, with the full minimum-elements
battery running on the primary. What remains FORBIDDEN is a second independent scan —
two scanners drift, and a consumer holding both learns nothing except that we disagree
with ourselves. The derive-once rule, applied to CI artifacts: one derivation, two
serializations, zero disagreement by construction.

### Canary Guard
----
RID: `req-cicd-sbom-7`
Status: `Implemented`

Before attesting, the pipeline MUST verify each generated SBOM **fail-closed** against a
canary list, refusing to publish on any miss:

* web MUST contain: `tap` at the built version, `django`, a known apk canary (e.g.
  `openssl`), and **every declared out-of-band component** (req-cicd-sbom-3: `fips.so`,
  `uv`, `uvx`);
* db MUST contain: `postgresql-16` and its declared out-of-band component (`fips.so`);
* both MUST NOT contain known-phantom markers (e.g. `my-test-package`, any
  `/opt/uv-cache-seed` location).

Rationale: every failure mode observed in the groundwork was *silent plausibility* — a
scan that succeeds and emits confident garbage. The canary guard converts "the SBOM
quietly went wrong" (cataloger regressed in a Syft bump, cache path moved, augmentation
step dropped) into a red publish. Canaries are deliberately TAP-specific truths; generic
structural well-formedness is req-cicd-sbom-11's job — the two validate different
failure classes at the same gate point. At implementation time this check is a validation
surface and gets its Validation Map row (spec-dev-validation.md) in the same change.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-7-1 | Honest document passes | Implemented | A document carrying the required canaries and every declared out-of-band component passes. | |
| req-cicd-sbom-7-2 | Dropped declaration is a red | Implemented | Omitting any declared out-of-band component (fips.so, uv, uvx) fails the guard. | |
| req-cicd-sbom-7-3 | Missing tap itself is a red | Implemented | A plausible SBOM missing the `tap` component fails. | |
| req-cicd-sbom-7-4 | Phantoms are a red | Implemented | A known phantom name or a component located under the wheel-cache path fails. | |

### Release SBOM Diffs
----
RID: `req-cicd-sbom-8`
Status: `Backlog`

A human-readable package delta between consecutive release SBOMs (added / removed /
version-changed, OS layer and Python closure), attached to the release. This is the
machine-checkable half of the customer upgrade-diff promise: release notes describe
source changes; the SBOM diff surfaces the silent package drift underneath
(`req-cicd-product-releases`). Deferred: pure consumer of req-cicd-sbom-1..7, adds no
constraint on them, and should be built against real release cadence.

### Flavored Ready-Made Images
----
RID: `req-cicd-sbom-9`
Status: `Proposed`

TAP is tacking toward **ready-made appliance images**: a boot profile's plugin set baked
into a published image (e.g. a GitHub-configuration mapping instance), pulled from the
registry with everything installed — an adopter slots in secrets and boots. This
requirement is a **design constraint on req-cicd-sbom-1..7 now** and an implementation
obligation when those images ship:

* A flavored image's SBOM MUST cover the core closure **plus the baked plugin closure**
  (each plugin and its dependencies), derived by the same principle as everything else:
  from **declared, hash-verified manifests baked in the artifact** — the core `uv.lock`
  plus the flavor's boot-profile plugin manifest (the boot-record-as-BOM data, which
  already names each plugin at an exact version) — never by scanning materialized
  caches or installed trees (the wheel-cache phantom lesson applies with more force,
  since plugin wheels ride the same cache mechanism).
* Therefore the generation step (req-cicd-sbom-1) MUST be parameterized as *artifact ×
  list-of-declared-manifests*, not hardcoded to "two images, one lockfile each"; the
  canary guard (req-cicd-sbom-7) MUST take per-flavor canary lists (every baked plugin
  present; the flavor's profile named).
* The boot record of a ready-made instance SHOULD reference the image SBOM (by image
  digest) for the baked set rather than restating it, and record only runtime deltas —
  one fact, derived once, linked across layers.
* Naming/tagging of flavored images follows the existing pipeline disciplines unchanged
  (digest-threading, per-arch, signed attestation home).

Status rationale: no flavored image exists yet, so nothing here is buildable — but
req-cicd-sbom-1/-7's implementation must not foreclose it. The extensibility is cheap at
design time and expensive to retrofit (the security-posture asymmetry).

### Plugin-Declared SBOMs
----
RID: `req-cicd-sbom-10`
Status: `Implemented`

**Declaration half BUILT and live-proven 2026-08-20**: the reusable release lane
(`.github/workflows/plugin-release-sbom.yml` + `scripts/sbom/plugin_release.py`) is
wired as a tag-triggered thin caller in ALL 12 plugin repos; pilot release
tap-plugin-aws-core v0.4.2 carries verified wheel provenance + both SBOM attestation
predicates (`gh attestation verify <wheel> --owner unified-systems-com [--predicate-type …]`). A wheel SBOM covers the plugin at its exact version plus
DECLARED dependency requirements — resolution deliberately absent (coverage statement
says where resolution truth lives). This requirement is scoped to the
DECLARATION half; the composition half (flavored-image bake-time derivation + boot
records referencing release SBOMs by digest) is req-cicd-sbom-15, riding the appliance
arc with req-cicd-sbom-9. Named gap, corrected 2026-08-20 after scouting: the secret-source
dist was RE-HOMED 2026-08-09 to `tap-build-dependencies` (old repo archived; core's
in-tree copy evicted; doc-github-org-migration-plan records it) — the gap belongs to
THAT repo: it has CI but no release tags (consumers pin SHAs) and no release-SBOM
lane, and its projects live in subdirectories, so serving it means generalizing this
lane with `dist_name` + `project_dir` inputs plus a multi-project tag convention
(`<dist>-vX.Y.Z`). Original requirement text follows.

Plugins declare their own SBOMs, on the **declare-vs-decide** pattern the manifest
`[fips]` table established: the author's pipeline DECLARES, the system VERIFIES and
COMPOSES — it never re-derives blindly and never trusts blindly.

* **Declaration at release time.** The shared plugin release lane (plugin CI /
  `release-plugin.sh`) generates each plugin's SBOM from its own declared manifests
  (pyproject + lock), CycloneDX, published as a signed attestation against the release
  artifact — the same `attest-sbom` home and verify story as core (req-cicd-sbom-4).
  Identity keys on (package name, exact version): the boot-record entry key, so every
  layer joins on the same fact.
* **Composition, not re-scanning.** A flavored image build (req-cicd-sbom-9) VERIFIES
  each baked plugin's release-SBOM attestation; a running instance's boot record
  REFERENCES plugin SBOMs by digest/purl rather than restating them. Instance BOM =
  image-SBOM reference + per-plugin SBOM references + runtime deltas.
* **Derive-once at bake time.** A flavored image's true closure is the SINGLE bake-time
  resolution of core + plugins together (shared dependencies dedupe; version conflicts
  are the deps gate's job). The flavored artifact's SBOM therefore generates from that
  combined bake-time lock — one derivation. Plugin-declared release SBOMs serve the
  other two consumers: runtime (non-baked) installs, and the cross-check.
* **Declared-vs-derived cross-check.** What the bake derived MUST reconcile with what
  each baked plugin's author declared; a mismatch is a canary-guard red
  (req-cicd-sbom-7), never a silent preference for either side — disagreement between
  declaration and derivation is precisely the signal worth stopping for.
* **Trust rides the signing wave.** Plugin SBOM attestations inherit the org-rooted
  identity `req-tap-plugin-extdev-signing` lands
  (`tap_plugins/specs/spec-plugin-external-development.md`); no new trust machinery
  is invented here, and nothing blocks on it — GitHub-attested by CI is the interim
  posture; org-rooted plugin publisher identity hardening lands with
  `req-tap-plugin-extdev-signing`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-10-1 | Identity matches or fails | Implemented | The SBOM's plugin component must match the expected dist name at the exact tag version; a mismatch (e.g. a shallow checkout building 0.0.0) fails. | |
| req-cicd-sbom-10-2 | Absent component fails | Implemented | A wheel SBOM without the plugin's own component fails the identity gate. | |
| req-cicd-sbom-10-3 | Wheel exemption is scoped | Implemented | Minimum-elements-lite exempts only the dependency graph; structural failures still fail closed. | |

### Standards Conformance Validation
----
RID: `req-cicd-sbom-11`
Status: `Implemented`

Before attesting, each generated SBOM MUST pass, fail-closed at the same gate point as
the canary guard:

* **Schema validation of BOTH emitted documents** against their declared spec
  versions — CycloneDX against the bom schema, SPDX against the SPDX JSON schema
  (vendored, pinned copies: a conformance gate that fetches its schemas from the
  network at publish time would be its own supply-chain hole).
* **Minimum-elements field checks** (CISA/NSA 2026 minimum elements): format name +
  version, SBOM/document version, generating tool name + version, generation
  timestamp/context, author, per-component **identifiers** (purl/CPE where they exist)
  and **hashes**, **dependency relationships** (the graph, not a flat list — the
  generation step of req-cicd-sbom-1/-6 MUST emit it; lockfiles carry the edges), and a
  **coverage/completeness statement** naming what the document does and does not cover
  (the known-unknowns discipline — SPDX-style NOASSERTION honesty in CycloneDX terms).
* **Signature mapping stated, not pretended:** the minimum-elements "author signature"
  is satisfied at the ATTESTATION layer (req-cicd-sbom-4's Sigstore-signed statement
  binding document to digest and workflow identity), not by an in-document signature.
  The conformance check verifies the document is *attestable* (hash-stable,
  schema-valid); the signature lives one layer up. If a consumer ever requires
  in-document signing, that is a named extension, not a silent gap.

Division of labor with req-cicd-sbom-7: canaries catch TAP-specific lies (a plausible
SBOM missing `tap` itself); conformance catches malformed valid-looking documents (a
structurally hollow SBOM full of unidentifiable components). Both are validation
surfaces → Validation Map rows at implementation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-11-1 | Minimum elements pass and fail closed | Implemented | A conformant document passes; dropping serialNumber, timestamp, the dependency graph, the coverage statement, or a component's version each fails. | |
| req-cicd-sbom-11-2 | Identifier-coverage flood detected | Implemented | More than the tolerated handful of purl/CPE-less components fails with the offenders named. | |
| req-cicd-sbom-11-3 | Legacy tools array accepted | Implemented | CycloneDX's legacy tools-as-array serialization passes the tools check without error. | |

### Out-of-Band Detection Gate
----
RID: `req-cicd-sbom-12`
Status: `Proposed`

req-cicd-sbom-3's declaration duty MUST be **detected, never remembered**. Relying on an
author to recall the supplemental-entry rule while editing a Dockerfile is the opt-in
failure mode this spec exists to kill; the out-of-band inventory is deterministically
derivable, so derive it:

* **Authoring-time (Dockerfile-derived inventory).** Every out-of-band introduction
  site is statically enumerable from the Dockerfiles: `COPY --from=<external image>`
  (digest-pinned binary imports — `uv`/`uvx` today) and `COPY --from=<builder stage>`
  (self-built artifacts — `fips.so` today). A guard reconciles that derived set against
  the declared entries, both directions, and fails on any unmatched member (same
  harness family as the TAP-KNOWN-DUPE and workflow guards; ratchet-style, no
  baseline exceptions).
* **Publish-time (image-level unknowns budget).** After generation, every executable
  and shared object in the scanned image MUST be accounted for: owned by an apk
  package, a member of the locked closure, or covered by a declared entry. The
  remainder — Syft's `unknowns` class, where `fips.so` surfaced in the groundwork —
  MUST be empty; any unclassified executable is a red publish. This is
  `req-fips-crypto-bom`'s fail-closed-on-unclassified discipline generalized from
  crypto providers to all executable content, and it is ecosystem-agnostic by
  construction: a hand-built binary in ANY language trips it on arrival.
* **Deterministic source-built marking (Python).** The set of Python packages built
  from source is derivable, not declarable: `[tool.uv] no-binary-package` plus the
  lock's sdist entries name them. The SBOM MUST mark those components as
  built-from-source (with the build context), derived from that configuration — never
  hand-maintained.

### Ecosystem Coverage
----
RID: `req-cicd-sbom-13`
Status: `Proposed`

**Doctrine (George, 2026-08-20): adopt the ecosystem's own distribution system — never
roll our own.** Every package ecosystem present in a published artifact is consumed
through that ecosystem's native registry + lockfile + integrity format, and merged into
the SBOM approach at the LOCKFILE seam (the req-cicd-sbom-2 principle: derive from
declared, hash-verified manifests). The payoff is structural: the scanning, updating,
and advisory machinery of every ecosystem is built around its lockfile — Renovate,
Dependabot, Syft, and OSV all speak it natively — so adopting the standard buys the
SBOM slice, the update lane, and the vulnerability feed for free, while a parallel
hand-rolled distribution mechanism must rebuild all three and then maintain the
imitation forever. TAP's custom surface per ecosystem is deliberately confined to
**acquisition wiring** (fetch-verify-place inside the attested build) and the
fail-closed gates.

Per-ecosystem application:

* **Python** — covered: PyPI + `uv.lock`, hash-verified at acquisition, the -2
  derivation. The reference implementation of this requirement.
* **JavaScript — the NAMED EXISTING GAP, and the doctrine's first test.** Third-party
  JS currently ships as hand-vendored minified files (`tabulator.min.js`,
  `echarts.min.js`, `htmx.min.js`, `cytoscape.min.js` + tabulator css) — three of the
  five version-anonymous, invisible to every scanner and updater. The fix shape:
  `package.json` + `package-lock.json` in-repo as the declaration, acquisition by
  **`npm ci --ignore-scripts` in a digest-pinned node BUILDER stage** — the
  ecosystem's own acquisition tool, used the standard way, per this requirement's
  doctrine (a lock-parsing curl fetcher was considered and REJECTED as rolling our
  own npm client: npm versions the lock format, and `npm ci` is the reference
  implementation of its semantics). Same builder-stage boundary as `ossl-builder`
  and `deps-warm`: node never ships in the runtime image or touches the dev loop;
  `--ignore-scripts` closes the install-script vector, safe by construction since
  the stage extracts static assets and executes nothing. Only the dist files are
  copied out, to an image path outside the dev bind mount (`STATICFILES_DIRS`),
  bytes leaving git. Renovate maintains the lock natively; the lockfile in-repo feeds the
  dependency graph and Dependabot automatically; Syft's npm-lockfile cataloger joins
  the -1 derivation exactly as uv.lock does. First step regardless of shape: identify
  the four anonymous files' exact versions by hash-matching upstream release
  artifacts (any file matching NO release hash is an undeclared fork and must be
  surfaced, never silently re-pinned).
* **Rust (first-party, future)** — crates.io + `Cargo.lock`; `cargo-auditable`'s
  embedded metadata rides in the binary (the -2 exclusion applies only to third-party
  tool binaries whose closure is not ours; a first-party binary's closure is INCLUDED).
* **Go (future)** — module proxy + `go.sum`.
* **Hand-authored vendored-asset manifests (the Chromium `README.chromium` /
  `moz.yaml` pattern) are the LAST RESORT**, reserved for artifacts with no registry
  standard at all — which is the niche those conventions were actually built for
  (C/C++ vendoring). Each such manifest is a named debt carried in this requirement,
  never a pattern to extend. None exist today.

New ecosystems need no spec amendment to be caught: an unmanifested binary trips the
req-cicd-sbom-12 budget on arrival, and this requirement names the duty its author
then owes — adopt the ecosystem's standard, wire acquisition into the attested build,
select its lockfile cataloger into the derivation.

### Consumer Verification Docs
----
RID: `req-cicd-sbom-14`
Status: `Proposed`

The canonical resolve-and-verify flow (req-cicd-sbom-5) MUST be carried verbatim in the
release/consumer documentation. Blocked on that surface existing — TAP has no
consumer-facing release docs home yet; when one lands (the Sam-facing adopter docs are
the likely vehicle), this requirement names the obligation that the flow lives there,
not only in this spec.

### Plugin SBOM Composition
----
RID: `req-cicd-sbom-15`
Status: `Proposed`

The composition half of req-cicd-sbom-10, split out so the declaration half's status can
be honest: a flavored ready-made image's SBOM derives ONCE from the bake-time combined
lock and MUST reconcile against each baked plugin's declared release SBOM
(declared-vs-derived disagreement is a canary red, req-cicd-sbom-7); a running
instance's boot record references plugin release SBOMs by digest/purl rather than
restating them — instance BOM = image-SBOM reference + per-plugin SBOM references +
runtime deltas. Rides the appliance arc with req-cicd-sbom-9; the fleet-wide plugin
release SBOMs (2026-08-20) are the ready inputs.

## Non-Goals and Named Residuals

* **Runtime-added plugin SBOMs** — the boot record is the instance-level BOM for
  anything installed at boot rather than baked; out of scope here. The baked-plugin case
  is IN scope via req-cicd-sbom-9. Future seam (named, not built): the boot record
  references the image SBOM by digest rather than restating it — one fact, derived once,
  linked across layers.
* **Registry-side referrers copy** — deferred, see req-cicd-sbom-4.
* **Build-cache poisoning** — upstream of generation entirely; named and accepted at
  `req-cicd-supply-chain-provenance-1`. An SBOM inventories what was built; it cannot
  vouch that the build inputs were honest — that is provenance's job.
* *(SPDX emission was listed here as deferred; review moved it into day-one scope —
  req-cicd-sbom-6 now emits both formats from the single derivation.)*
