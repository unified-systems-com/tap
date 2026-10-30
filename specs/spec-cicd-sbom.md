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
| req-cicd-sbom-4 | [Signed Digest-Bound Home](#signed-digest-bound-home) | Implemented | `actions/attest` (sbom-path) per arch digest, GitHub attestation store; digest-threading law applies end to end; registry copy (if ever) must be a signed attestation, never an attachment; **a versioned release verifies them before it is tagged, and `:latest` moves only after they exist** (tap#525) |
| req-cicd-sbom-5 | [Per-Arch Standalone SBOMs](#per-arch-standalone-sboms) | Implemented | One SBOM per platform digest; no merged index-level SBOM exists |
| req-cicd-sbom-6 | [Single Derivation, Format as Serialization](#single-derivation-format-as-serialization) | Implemented | One Syft scan per digest is canonical; CycloneDX JSON + SPDX JSON BOTH emitted from that same scan on day one; CycloneDX primary |
| req-cicd-sbom-7 | [Canary Guard](#canary-guard) | Implemented | Fail-closed publish check: expected components present, known phantoms absent — else no attestation |
| req-cicd-sbom-8 | [Release SBOM Diffs](#release-sbom-diffs) | Backlog | Human-readable package delta per release, feeding the customer upgrade-diff contract; consumer of 1–7, not a blocker |
| req-cicd-sbom-9 | [Flavored Ready-Made Images](#flavored-ready-made-images) | Proposed | Design constraint now, implementation with the appliance-image work: an image baking a boot profile's plugins ships an SBOM covering core + baked plugin closure, from the same declared-manifest principle |
| req-cicd-sbom-10 | [Plugin-Declared SBOMs](#plugin-declared-sboms) | Implemented | Declare-vs-decide: plugin release CI declares an attested per-release SBOM; the system verifies and composes, never re-derives blindly; bake-time combined lock is the single derivation for flavored images |
| req-cicd-sbom-11 | [Standards Conformance Validation](#standards-conformance-validation) | Implemented | Schema-validate the CycloneDX document + fail-closed minimum-elements field checks (CISA/NSA 2026); canaries catch TAP-specific lies, this catches malformed valid-looking SBOMs |
| req-cicd-sbom-12 | [Out-of-Band Detection Gate](#out-of-band-detection-gate) | Implemented | Declaration is DETECTED, never remembered — all three pieces live: Dockerfile COPY --from reconciliation fail-closed per-commit (PATHS: that every site is declared — the declared VERSION is not reconciled here because it is no longer declared, it is derived, req-cicd-sbom-3-4); unknowns budget fail-closed per-publish per-arch (flipped on a proven 0/0/0/0); source-built set derived from no-binary-package + sdist-only lock entries and marked at generation, fail-closed on absence |
| req-cicd-sbom-13 | [Ecosystem Coverage](#ecosystem-coverage) | Implemented | Doctrine: adopt each ecosystem's OWN distribution system and merge at the lockfile seam. JS gap CLOSED: package-lock + `npm ci --ignore-scripts` js-vendor stage, all five files hash-matched upstream (no forks), echarts XSS surfaced+fixed by the native tooling on day one; hand-authored manifests remain last-resort named debt |
| req-cicd-sbom-14 | [Consumer Verification Docs](#consumer-verification-docs) | Proposed | The req-cicd-sbom-5 resolve-and-verify flow carried verbatim in the release/consumer documentation, once that surface exists |
| req-cicd-sbom-15 | [Plugin SBOM Composition](#plugin-sbom-composition) | Proposed | The composition half of -10: bake-time single derivation reconciled against plugin-declared SBOMs; boot records reference release SBOMs by digest — rides the appliance arc with -9 |
| req-cicd-sbom-16 | [Crypto Bill of Materials (CBOM) in the Image SBOM](#crypto-bill-of-materials-cbom-in-the-image-sbom) | Proposed | Close the CBOM gap inside the existing single derivation: `tap.crypto_bom` findings and dispositions ride the attested CycloneDX document as `tap:crypto:*` properties on the owning component; one document, one predicate. Providers only in the first slice; other assetTypes named, sourced and deferred. Ingestion verifies the attestation before it parses. |
| req-cicd-sbom-17 | [Vulnerability Evidence Workflow](#vulnerability-evidence-workflow) | Proposed | ONE reusable CI workflow teams call: Syft CycloneDX 1.7, scan, merge, enrich, validate, attest; rescan mode; scanners in an unsigned job, a first-party job signs. Overview and the nine-decision ledger precede it. |
| req-cicd-sbom-18 | [Merge and Enrichment](#merge-and-enrichment) | Proposed | Join scanner output by purl (Grype keeps 1 of 191 bom-refs); per-entry `tools`; dedupe with GHSA/CVE aliases; CVSS, CWE, SSVC (CISA-ADP), KEV (catalog-stamped), EPSS, each with provenance |
| req-cicd-sbom-19 | [Scan Coverage - SBOM Scan and Image Cross-Check](#scan-coverage---sbom-scan-and-image-cross-check) | Proposed | Decided SV-2: scan both; the SBOM scan is the record, the image scan reports differences |
| req-cicd-sbom-20 | [Document Revisions - One Merged Document](#document-revisions---one-merged-document) | Proposed | Decided SV-1: one merged document; each scan is the next `version` of the SAME `serialNumber`; all revisions kept (revisit); signature = CI ran the named tools |
| req-cicd-sbom-21 | [Deploy Gate](#deploy-gate) | Proposed | Decided SV-5: block promotion of a KEV-listed image against the CURRENT catalog; fail closed; waiver path UNRULED |
| req-cicd-sbom-22 | [Signer Trust](#signer-trust) | Proposed | Decided SV-8: default-deny signer list as data, one starting signer (the reusable workflow, pinned ref and signer digest); signature time is the log time |
| req-cicd-sbom-23 | [Dependabot Intake](#dependabot-intake) | Proposed | Decided SV-7: fetch in CI; fork and Dependabot runs record `not-observed`, never an empty list; permission claim NOT OBSERVED |
| req-cicd-sbom-24 | [Ingestion - SBOM Node, Parser and Ownership](#ingestion---sbom-node-parser-and-ownership) | Proposed | Decided SV-3: computing_core owns node and parser; verify first, parse only the verified predicate; metadata plus file reference, not the document |
| req-cicd-sbom-25 | [Idempotency and Duplicates](#idempotency-and-duplicates) | Proposed | Document identity is the content digest; stable finding keys; unreported means resolved; counts group by (vulnerability, component version) |
| req-cicd-sbom-26 | [Current Semantics, Counting and Triage](#current-semantics-counting-and-triage) | Proposed | Current = highest revision per digest; fleet counts over deployed images; triage judgements survive a new image |
| req-cicd-sbom-27 | [Alert-Derived and SBOM-Derived Duplicates](#alert-derived-and-sbom-derived-duplicates) | Proposed | Decided SV-6: keep both and correlate on (vulnerability, component version, image); alerts give first-seen and dismissal, the SBOM gives presence now; retire alert component findings later |
| req-cicd-sbom-28 | [Dependency Links as Edges (Provisional)](#dependency-links-as-edges-provisional) | Proposed | Decided SV-4: `dependsOn` becomes `REQUIRES_PACKAGE` edges, plain identity, provisional with revisit conditions |
| req-cicd-sbom-29 | [Scanner Pin Maintenance](#scanner-pin-maintenance) | Proposed | Decided SV-9: Renovate managers for the Syft and Grype pins in one group (build later); Trivy waits on tap#1038 |
| req-cicd-sbom-30 | [What This Feeds - CBOM and VDR](#what-this-feeds---cbom-and-vdr) | Proposed | How this feeds `req-cicd-sbom-16` and what a VDR consumer needs from the grid (VDR itself not specified) |
| req-cicd-sbom-32 | [SBOM Field Completeness Check](#sbom-field-completeness-check) | Proposed | A CI check that an SBOM carries the fields the grid and Grype match on (full purl qualifiers, CPE, apk origin, distro component); a thin SBOM is refused or visibly flagged, never silently under-reported |
| req-cicd-sbom-33 | [Python Wheel Attributes - License and Architecture](#python-wheel-attributes---license-and-architecture) | Proposed | The locked Python components carry a license and an architecture, read from the wheels in the image's cache seed and joined to the lockfile closure; unknown is declared, never silent |

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

Each SBOM entry carries, at minimum: component name, **version**, **source** (for
copied binaries: the upstream image ref + digest; for self-built: the pinned source URL),
**file path in the image**, **SHA-256 of the file**, **license**, and a **purl/CPE where
one exists**.

**Which of those the manifest AUTHORS, and which generation DERIVES** (tap#225). The
manifest declares what only a human can say — identity, path, license, rationale, the
version-free `purl_base`. Every fact the build already states is derived at generation
time and MUST NOT appear in the manifest:

| Fact | Authoring site | How the entry gets it |
| --- | --- | --- |
| file SHA-256 | the built artifact | hashed from the scanned image, per-arch |
| copied-image version + source ref + purl | the `COPY --from=<repo>:<tag>@sha256:<digest>` line | `generate.derive_copied_image_facts` joins manifest→Dockerfile on `path` |
| self-built FIPS provider version | `docker/build-openssl-fips.sh` (`OSSL_VERSION`) | `tap/fips_pins.py`; the manifest's `version`, `source`, `purl` and `cpe` are **verified** against it and fail closed |

The derivation is remedy #1 of *derive > verify > detect*: the second copy is removed, so
it cannot drift. It was not a hypothetical. The supplemental declared `uv` **0.12.3**,
with a digest to match, while the image shipped 0.12.7 and then 0.12.15 — Renovate's
`dockerfile` manager bumps the pin and nothing bumped the manifest, so the published,
**attested** SBOM asserted contents that were not in the image and grew more wrong with
every release. The reconciliation gate (req-cicd-sbom-12) did not catch it because it
checks that every `COPY` path is DECLARED, never that the declared version is TRUE: a
presence test wearing a correctness test's clothes.

The manifest's own `_description` had predicted the failure ("Version must match the
Dockerfile COPY pin (reconciled by the req-cicd-sbom-12 guard when it lands)") and the
note outlived the guard's landing. Deriving retires the note rather than delivering the
reconciliation it anticipated — and it is the decision this file had already made once,
for the file hash, and stopped one field short of.

The self-built provider keeps authored `source`/`purl`/`cpe` on purpose: the release-URL
shape is constructed once in `docker/build-openssl-fips.sh` from `OSSL_VERSION`, and
restating that construction in Python would trade one duplicate for another across a
language boundary. The fact that drifts — the version — is derived from the pin, and the
three fields that spell it out are checked against it. `OSSL_SHA256` and
`OSSL_SIGNING_PRIMARY` stay hand-authored because they are **assertions, not copies**: a
digest derived from the file it checks verifies nothing.

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
| req-cicd-sbom-3-4 | Copied-image facts are derived | Implemented | A copied-image component's version, source ref and purl are derived at generation time from the `COPY --from` pin that lands its path — never read from the manifest. A bumped pin therefore produces a correct SBOM with no second edit. | tap#225: the declared uv version was four releases stale in a published, attested SBOM. `generate.derive_copied_image_facts`; `tap/tests/test_sbom_generate.py`. |
| req-cicd-sbom-3-5 | Authoring a derived fact is a red | Implemented | A copied-image entry that declares `version`, `source` or `purl` fails BOTH the JSON Schema and the generator, and a declared path fails the generator unless EXACTLY ONE `COPY --from` site writes it and that site is a fully pinned `<repo>:<tag>@sha256:<digest>` image — a half-pinned or stage-name reference is never treated as a version, and two sources writing one path is refused rather than resolved. | Removing the copy only helps if it cannot come back; the second half of this is the "NOT OBSERVABLE is not absent" rule — an underivable component must not publish as though its provenance were known. The parser reads instructions, not the stage graph, so it cannot say which of two writers ships; picking the textually last one would be an assumption dressed as a derivation (Codex review seat, PR# 627 - tap). Residuals, named not implied: a plain `COPY` from the build context over a declared path is invisible to it (tap#642), and the tag a version is read from is not itself proven to match the digest's bytes (tap#643). |
| req-cicd-sbom-3-6 | Self-built version claims are verified | Implemented | For the self-built FIPS provider the manifest's `version`, and every version-bearing identity field (`source`, `purl`, `cpe`), are compared against the pin in `docker/build-openssl-fips.sh` and fail closed on disagreement. | Remedy #2 where #1 does not fit; a stale `cpe` is the worst of the three, since it silently matches the advisory feed for a version the image does not ship. |

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

Since tap#507 the document DOES travel by artifact: generation runs on a read-only token
(`sbom` job) and signing in a first-party-only job (`attest-sbom`), so no third-party code
shares the signing token. The signing job re-binds before it signs, fail-closed: each
document must name, in its own content, the image ref and the exact per-arch digest it is
about to be attested against (CycloneDX `metadata.component`; SPDX's DESCRIBES-ed CONTAINER
package). Residual, named: the split protects the token, not the content — a compromised
generation dependency could still produce a false document bound to the right subject.

**The release gate (tap#525, 2026-09-19).** Producing an attestation and *releasing only
what carries one* are two different guarantees, and TAP had only the first. `publish-release-tags`
polled until `:sha-<short>` EXISTED and promoted it to `:X.Y.Z` — presence read as completeness —
so for 15 days (tap#518), and again on the next change (tap#543), versioned tags were cut from
images whose SBOM attestations had never been produced, with every workflow green. Two changes
close that:

- **Before a version tag is created**, `retag` verifies SLSA provenance on the index digest and
  BOTH SBOM predicates on every per-arch child (`gh attestation verify --predicate-type`), and
  refuses otherwise. Three states, two of which block: *verified*; *MISSING* (the subject exists,
  the attestations API answers 404); *NOT OBSERVABLE* (the check could not complete). A check that
  could not look must never render as nothing-to-find. Counts are not a verdict — an unchanged
  image is re-attested on every publish, so ≥1 verifying bundle is the predicate.
- **`:latest` moves last**, in `promote-latest`, which waits on `attest-sbom`. `:sha-<short>` is
  still minted by the merge step because an OCI index cannot exist untagged and every attestation
  binds to those digests; the mutable pointer consumers follow is what waits.

Neither workflow can be exercised by PR CI (tag-push and main-push triggers), which is how both
failures shipped green; `tap/tests/test_release_gates.py` asserts the ordering statically and
executes the gate's own `run:` body against stub `docker`/`gh` to prove all three outcomes.

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
* db MUST contain: `postgresql-18` and its declared out-of-band component (`fips.so`);
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
arc with req-cicd-sbom-9. Named gap CLOSED 2026-08-21: the secret-source dist (RE-HOMED
2026-08-09 to `tap-build-dependencies`; old repo archived, core's in-tree copy evicted,
doc-github-org-migration-plan records it) now rides the SAME lane — generalized with
`dist_name` + `project_dir` inputs and prefixed-tag parsing under the org tag grammar
`[<dist-name>-]vX.Y.Z` (req-cicd-release-artifacts in [spec-cicd-hardening.md](spec-cicd-hardening.md),
which owns the artifact-class model this lane serves); `aws-secrets-source-v0.2.0` is the first
prefixed-tag release. Original requirement text follows.

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

Status: `Implemented`

**Staging (2026-08-24):** the authoring-time Dockerfile guard is LIVE and fail-closed
(`scripts/sbom/oob_detect.py --dockerfile`, run as a unit test): every `COPY --from`
site must resolve to declared supplemental-manifest path(s) or carry an explicit
`# sbom-allow(<rid>): <reason>` annotation on the preceding comment line (Dockerfiles
have no trailing comments; the annotation binds to the next instruction only). The
publish-time unknowns budget (`--unknowns <image-ref> --fail`) is **FAIL-CLOSED since
2026-08-24**: an executable no apk package owns, no supplemental entry declares, and
no exclusion covers kills the publish before attestation. Flipped per its own staging
— dry run first (0 unknowns on both images, after two corrections the dry run itself
surfaced: apk ownership lives in the package's file INVENTORY, not its syft locations;
Wolfi's `usr/lib64` aliasing hides libffi from even `apk info --who-owns`), then one
green publish (run 32686098463) proving 0 on all four per-arch digests with the
js-vendor stage included, then the flip. Only FINDINGS were ever report-only;
operational failures always failed the job. The third piece, deterministic source-built
marking, is IMPLEMENTED: the built-from-source set is derived (never declared) from
`[tool.uv] no-binary-package` + the lock's sdist-only entries and marked in BOTH
serializations at generation (`tap:source-built` properties / SPDX comments), fail-closed
when a derived member is absent from the scan. First derived set: cryptography (forced,
the FIPS --no-binary discipline), psycopg-c + crontab (sdist-only upstream).

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

  **What this gate does and does not decide.** It reconciles **paths**: that every site
  lands a declared path, or carries an `sbom-allow`. It does not check that a declared
  **version** is true, and it must not be extended to — the version is no longer declared
  anywhere for it to check (req-cicd-sbom-3-4 derives it from the very pin this gate
  parses). Saying so here is the point: for four uv releases this gate was cited as the
  thing that kept the SBOM honest about versions, which it never was (tap#225). One
  parser serves both readers — `generate.parse_copy_sites` — so the set of sites this
  gate reconciles and the set generation derives from can never diverge.
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

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-12-1 | Undeclared COPY --from fails | Implemented | A `COPY --from` site whose destination path(s) are neither declared in the image's supplemental manifest nor covered by an `sbom-allow` annotation is a red. | The live authoring-time guard; both real Dockerfiles reconcile green against their real manifests. |
| req-cicd-sbom-12-2 | Annotations bind narrowly | Implemented | An `sbom-allow` annotation covers only the immediately following instruction — it never floats down the file to excuse later sites. | Prevents one blessed exception from silently blessing the next addition. |
| req-cicd-sbom-12-3 | Directory destinations compute per-file | Implemented | A dir-destination copy (`COPY --from=... /a /b /dest/`) is satisfied only when EVERY computed destination path is declared — one declared file cannot carry an undeclared sibling. | The uv/uvx two-binary site is the live example. |
| req-cicd-sbom-12-4 | Exemptions cite real rules | Implemented | An `sbom-allow` annotation exempts only when it names a requirement DEFINED in the spec tree AND carries a non-empty reason — a made-up id or a bare tag is a red, not a pass. | Codex/Grok finding on PR #115; a central exemption baseline/ratchet is the named future tightening if annotation count grows. |
| req-cicd-sbom-12-5 | Every spelling is seen or refused | Implemented | The parser handles case-insensitive instructions, reordered flags, line continuations, and JSON exec form; a COPY that mentions `--from` but resists parsing FAILS CLOSED rather than passing unexamined. | Codex bypass finding on PR #115: a guard that recognizes one spelling is a guard in name only. |
| req-cicd-sbom-12-6 | Source-built set is derived and marked | Implemented | The built-from-source members come from `[tool.uv] no-binary-package` plus sdist-only lock entries — never a hand-maintained list — and are marked in the generated SBOMs; a derived member absent from the scan fails generation. | The FIPS --no-binary builds (cryptography, psycopg-c) are the motivating members. |

### Ecosystem Coverage
----
RID: `req-cicd-sbom-13`

Status: `Implemented`

**JS gap CLOSED 2026-08-24, exactly on the doctrine's rails.** Identification pass
first: all five hand-vendored files hash-matched their npm release artifacts
byte-for-byte (htmx.org@2.0.4, echarts@6.0.0, cytoscape@3.30.4,
tabulator-tables@6.3.0 js + css) — no forks, no local patches, lossless migration.
The native tooling paid for itself on first contact, twice: `npm install` surfaced the
TRUE closure (echarts pulls `zrender` + `tslib` — dependencies the hand-vendoring
silently hid), and `npm audit` flagged the shipped echarts 6.0.0 with a known
moderate XSS (GHSA-fgmj-fm8m-jvvx) that nothing had been tracking — fixed by pinning
6.1.0 in the same change. Shipped shape: root `package.json` (exact pins) +
`package-lock.json`; `npm ci --ignore-scripts` in the digest-pinned `js-vendor` stage
(node + npm from Wolfi's apk repository on the pinned wolfi-base; originally node from
the ECR mirror); files staged under their historical app-relative static names into `/opt/tap-static-vendor` (outside the dev bind mount,
`STATICFILES_DIRS` guarded on existence so legacy images still boot); the lock rides
into the image and the scan catalogs it (`+javascript-lock-cataloger`); the four
libraries are publish canaries (req-cicd-sbom-7) so a dropped lockfile seam reds the
publish; the vendored bytes left git. Original doctrine text follows.

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

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-13-1 | JS closure is canaried | Implemented | All four vendored browser libraries are required publish canaries for the web image — a package-lock seam that stops being cataloged reds the publish, never silently shrinks the SBOM. | |
| req-cicd-sbom-13-2 | Exact pins + integrity | Implemented | `package.json` declares exact versions (no ranges — the build is the artifact pin, updates are reviewed lock diffs) and every `package-lock.json` resolution carries an integrity hash. | The npm analog of uv.lock's hash-verified acquisition. |

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

### Crypto Bill of Materials (CBOM) in the Image SBOM
----
RID: `req-cicd-sbom-16`

Status: `Proposed`

**What a CBOM is.** A CBOM is a bill of materials for cryptography: not "which packages are inside" but "which cryptographic
implementations, algorithms, protocols, certificates and key material are inside, and what was decided about each". There is no
separate CBOM format. CycloneDX 1.6 added the `cryptographic-asset` component type and a `cryptoProperties` block with four
`assetType` values: `algorithm`, `certificate`, `protocol`, `related-crypto-material` (read: `scripts/sbom/schemas/bom-1.6.schema.json`,
`definitions.cryptoProperties`). CycloneDX is also the Ecma standard ECMA-424: 1st edition = CycloneDX 1.6, 2nd edition = CycloneDX 1.7
(read: the Ecma-TC54/ECMA-424 repository README, <https://github.com/Ecma-TC54/ECMA-424>, which lists the 1st edition as v1.6 and the 2nd as
v1.7; the 2nd edition was published December 2025 per a web search of <https://tc54.org/cyclonedx/> and
<https://ecma-international.org/publications-and-standards/standards/ecma-424/>, search snippet, not read in full. The README did not
itself mention CBOM; that ECMA-424 covers cryptographic assets is the search snippet's wording and is NOT separately observed in the standard's text).

**The gap, measured.** `tap.crypto_bom` (`req-fips-crypto-bom`, Implemented) fingerprints native artifacts and gives each a disposition, as
a scan, a CI gate and a boot gate. It emits no CycloneDX (ran: `grep -rl cryptoProperties` over the tree matches only the vendored
`scripts/sbom/schemas/bom-1.6.schema.json`; the real tap-web:0.2.2 attestations, parsed, contain neither `cryptoProperties` nor a
`cryptographic-asset` component). What the attested SBOM already carries is one crypto fact: the self-built `openssl-fips-provider`
supplemental component with a derived `tap:fips-validation` property (read: both per-arch documents, 1 of 191 components). So the
published, signed, per-digest artifact says that a FIPS provider is present and its validation status, and does not say which of the
other binaries route through it, which are out of boundary, or what was decided. That last part lives only in a scan result.

**Why this is not a new pipeline.** Everything a CBOM document needs to be trustworthy already exists in this lane: a per-digest
derivation (`-1`, `-6`), out-of-band merging into the same document (`-3`), schema and minimum-elements validation (`-11`), a Sigstore
attestation bound to the digest with a release gate (`-4`), and a verify command. The missing piece is one more merge into the single
derivation, and a consumer that reads it.

#### Decision 1 - Scope: providers first; every other assetType named with its source

| assetType | In the first slice? | What it would need | Source that could supply it | Method |
| --- | :---: | --- | --- | --- |
| (provider) | Yes | A record of each crypto implementation found in an artifact and its disposition. CycloneDX has no provider assetType: the four values are algorithm, certificate, protocol, related-crypto-material, so a provider is a software component, not a cryptographic-asset | `tap.crypto_bom` findings (artifact path, provider, `Boundary`, rationale, rid) | read (schema enum; `tap/crypto_bom.py` `Finding`) |
| `algorithm` | No | Names of algorithms actually available and approved, with `primitive`, `certificationLevel`, `implementationPlatform` | NOT derivable from binary fingerprinting (the byte signatures name a provider, not its algorithms; `tap/crypto_providers.py` `SIGNATURES`). Candidate sources, each unverified for fitness: the validated module's own listing (`openssl list -digest-algorithms` etc. with the `fips` provider), the CMVP security policy for the certificate, or Python's `hashlib`/`cryptography` capability listing | read (signatures); ran: in the stat-card stack `openssl list -providers` shows `fips` 3.5.8 active and `-digest-algorithms` 74 lines, `-cipher-algorithms` 206, `-kdf-algorithms` 10, `-mac-algorithms` 6, `-signature-algorithms` 53 with `-provider fips -provider base` (line counts include aliases and headers, not a count of distinct algorithms). Whether the list is the approved subset is NOT OBSERVED |
| `protocol` | No | TLS/SSH versions and cipher suites a service is configured to accept | Declared configuration (openssl.cnf, the web tier's TLS settings, `libpq` `sslmode`), not binaries. Instance-level (what this deployment configures), so it belongs to the boot record before it belongs to the image | inferred |
| `certificate` | No | Subject, issuer, validity, signature algorithm | Deployed certificates exist at runtime (and `ca-certificates-bundle` is an apk, whose roots are data in a package). Instance-level; a collector, not the image derivation | inferred |
| `related-crypto-material` | No, deliberately | Keys, secrets, tokens: metadata only (type, state, `securedBy`) | The secret-source and `manage-secret` surface. The `value` field MUST NEVER be populated, and `crypto_provider` already refuses any key-material column (the no-key-material criterion of the `crypto_provider` model in the computing-core-tap spec) | read (computing-core spec); inferred (source) |

The artifact-versus-instance boundary of this spec's Philosophy applies unchanged: the image CBOM covers what every copy of this version
contains; configured protocols and live certificates are the instance's and ride the boot record or a collector.

#### Decision 2 - Mapping: a finding becomes properties on the owning component

A provider is not a cryptographic-asset, so the registry's vocabulary rides as `tap:`-namespaced properties on the component that owns the
artifact, the pattern this document already uses (`tap:fips-validation`, `tap:source-built`, `tap:path`) and the pattern Syft uses for repeated
facts (indexed names such as `syft:metadata:provides:0`, read in the real documents).

| Finding field | CycloneDX home | Note |
| --- | --- | --- |
| `provider` | `tap:crypto:<n>:provider` | the registry's name, verbatim (`openssl-system`, `rust-aws-lc-rs`, ...) |
| `boundary` | `tap:crypto:<n>:boundary` | exactly the five `Boundary` values; the disposition lives HERE and nowhere else in the document |
| `artifact` | `tap:crypto:<n>:artifact` | the path in the image, as `crypto_bom` reports it |
| `detail` / rationale | `tap:crypto:<n>:rationale` | the registry's reviewed sentence |
| `rid` | `tap:crypto:<n>:rid` | the requirement the disposition cites |

`<n>` is a per-component index. Owner resolution is the new work: the SBOM documents carry no file-to-package ownership (read: apk components
have `syft:location:0:path` = the apk database path, no per-file list, and no `evidence`), so the generator must derive the owner. For apk, the
file inventory the unknowns budget already reads (`scripts/sbom/oob_detect.py`, `req-cicd-sbom-12`); for files under the Python environment, the installed
distribution's RECORD (the derivation `req-fips-crypto-bom-waiver-ownership` proposes for waivers; the two SHOULD share one function); for
supplemental entries, the declared `tap:path`. **A finding whose owner cannot be resolved is never dropped**: it becomes a standalone component
of type `file` carrying the same properties, and the unowned count is reported in the coverage statement.

Rejected: (a) one `file` component per finding, always. It would add roughly 30 components to a 191-component document (ran: 30 findings in the
stat-card tap-web image) and pollute the package diff of `req-cicd-sbom-8`; kept only as the fallback above. (b) `cryptographic-asset` with
`assetType: algorithm` per provider. It asserts algorithms the scan did not observe, which is the plausible-but-wrong SBOM this spec exists to prevent.

`cryptographic-asset` components are reserved for Decision 1's later rows and are added only when a real source for them exists. Where they
are, the `dependencies[].provides` field (present in the vendored schema, read) links an owning component to the assets it implements.

#### Decision 3 - Placement: inside the single derivation, one document, one predicate

The CBOM is a **section of the existing CycloneDX document**, merged during generation like the supplemental components (`-3`) and the
source-built marks (`-12`), not a second scan and not a second attested file. `req-cicd-sbom-6` forbids a second independent scan of the same
facts; this is not one. Syft remains the sole component inventory, and `crypto_bom` observes a different fact (byte signatures in ELF files),
merged as annotations. Reasons for one document:

1. One attestation per digest and per predicate; the release gate (`-4`, tap#525) needs no new predicate and no new "missing attestation" state.
2. The consumer holds one hash-stable artifact answering "what is in it and what crypto does it use", and release diffs (`-8`) see one document.
3. The document is ~0.62 MB per arch (read: 615,427 and 624,316 bytes); a crypto section of tens of properties does not change that.

A separate CBOM document would be justified by: a CBOM-only consumer that rejects non-crypto components, or an independent release cadence. Neither
exists. If one appears, the answer is a **filtered view of this document** attested under a second predicate, never a rescan.

The scan input is the **exported filesystem of the verified per-arch digest**, using `scan()`'s explicit-roots interface (`req-fips-crypto-bom-3`), run by
first-party code in the generation job. It does not run the image's own copy of the scanner on itself. Binary roots map through the export prefix.

#### Decision 4 - Validation and attestation

* **Schema:** the document is already validated at generation. Read: `validate_schema` validates the CycloneDX document against the vendored **1.6** schema, and
  the real documents declare `specVersion: 1.7` (Syft 1.51.0). Both facts were read; whether 1.7 changed `cryptoProperties` relative to 1.6 is
  NOT OBSERVED (the 1.7 schema is not vendored). Before any `cryptographic-asset` is emitted, the vendored schema MUST match the emitted `specVersion`.
* **Fail-closed checks** (alongside `check_minimum_elements` and the canaries): every finding carries a disposition and a closed-vocabulary value; the sentinel
  of `req-fips-crypto-bom` holds in the document (the scan read binaries and saw `openssl-system` and the declared FIPS provider); the `tap:coverage` statement names
  providers as covered and algorithms, protocols, certificates and key material as not covered.
* **Attestation:** the existing `https://cyclonedx.org/bom` predicate, per arch digest, signed by the existing job. No new predicate type, because the document is the same document.
* **Ingestion verifies before it parses.** Ran, 2026-10-15: `gh attestation verify oci://ghcr.io/unified-systems-com/tap-web@sha256:d86ebb774dd2...0bc7 --owner
  unified-systems-com --predicate-type https://cyclonedx.org/bom --format json` exited 0 and returned one verified attestation. Its `statement.subject` digest was the
  requested digest, its `statement.predicateType` was `https://cyclonedx.org/bom`, and its signing certificate named
  `unified-systems-com/tap/.github/workflows/publish-images.yml@refs/heads/main`, a GitHub-hosted runner, at source commit `cbe3e700...`. The returned
  `statement.predicate` was byte-identical (canonical JSON) to the CycloneDX file another session had downloaded for that digest. So the parser MUST ingest the
  `statement.predicate` that verification returned, never a separately fetched file. What it proves: this document was signed by that workflow for that digest, recorded
  in the transparency log. What it does not: that the workflow's inputs were honest (the Residual named in `-4`), or that the cryptographic claims are right, only that TAP asserted them.

#### Decision 5 - Ingestion into the grid (the parser is shared with SBOM ingestion)

A CBOM parser is not a separate parser: it is the `tap:crypto:*` step of the one generic CycloneDX parser, because Decision 3 puts both in one document. What that
parser maps, with the computing_core vocabulary read from `specs/spec-computing-core-v0.md` in unified-systems-com/computing-core-tap:

| CycloneDX element | Grid result | Method |
| --- | --- | --- |
| the whole document | one SBOM node: metadata, subject digest, attestation reference and a reference to the stored file (the document is not stored in the database); owned by `computing_core` | George's rulings of 2026-10-15; `req-cicd-sbom-24` |
| `components[]` with purl type `apk`/`pypi`/`npm` | `package` keyed `(ecosystem = purl type, name, version)`; `purl`, `cpe`, `license` copied; `architecture` from the purl `arch` qualifier; `source_document: sbom` | read (spec); ran (101 apk, 71 pypi, 15 npm, 2 github, 1 generic, 1 without purl, in the real documents) |
| apk origin | `source_package` and `DERIVES_FROM_SOURCE_PACKAGE`, see below | ran |
| supplemental components (`tap:supplemental`) | `library` (and `SHIPS_LIBRARY` where a package ships it) | inferred from the `library` section of the computing-core-tap spec |
| `tap:crypto:<n>:*` | `crypto_provider` keyed `(scope, artifact, provider)` with `boundary` and `rationale`; `CARRIES_CRYPTO_PROVIDER` from the owning package/library | read (spec) |
| `metadata.component` (container, digest) | the image's host/OS context, `INSTALLS_PACKAGE` | Open Decision D |

**Convergence, not duplication.** `crypto_provider` nodes already exist (31 in the playground inventory bundle, per the support session's account; NOT OBSERVED by this
author). Parsed CBOM findings MUST produce the same identity `(scope, artifact, provider)` using the registry's own strings, so a parse updates those nodes and
creates none beside them. This is why Decision 2 keeps the artifact path and the provider name verbatim.

**The apk origin feeds `source_package` from the SBOM.** Verified on the real tap-web:0.2.2 documents (ran, both arm64 and amd64): `syft:metadata:originPackage` is present on
**101 of 101** apk components; the purl qualifier `upstream=` is present on **54 of 101**, exactly the components whose origin differs from their name (the other 47 are their own
origin, and the purl omits the qualifier). The property is therefore the complete source; the qualifier is a subset. The result is 69 distinct origins, 11 with more than one binary
package, which matches the apk-database observation recorded in the `source_package` section of the computing-core-tap spec (101 records, 69 sources, 11 multi-binary, 47 self-origin). In all 11 multi-binary
origins every member had one `version` string (ran). Neither source carries the origin's **version**; the node's key needs one, so it is taken from the member packages'
shared version (supported by the previous sentence and by the computing-core observation; a member with a differing version would be refused, not guessed). What this changes: nothing in the
types or edges; `source_package` and `DERIVES_FROM_SOURCE_PACKAGE` are unchanged. Only the feeder changes: the parser reads the SBOM instead of the apk database, and a join by source still never
needs a fallback branch because every package draws the edge.

#### Open decisions for the maintainer (not decided here)

* **A. Do the dependency links become edges?** DECIDED 2026-10-15 (George): yes for now, provisional; see `req-cicd-sbom-28`. The documents hold 458 `dependsOn` links on arm64 (356 apk to apk, 88 pypi to pypi, 14 npm to npm) and 420 on amd64 (318 apk) (ran). The options and recommendation first written here (none; a new edge; pypi/npm only) are superseded.
* **B. Who owns the SBOM node and the parser?** DECIDED 2026-10-15 (George): `computing_core`; see `req-cicd-sbom-24`. The recommendation first written here, a new `*_core` plugin depending downward on `computing_core`, is superseded, and no new plugin is created.
* **C. Which assetTypes after providers, and from which source?** Decision 1 lists candidates; none is chosen. Recommendation: stop at providers until a consumer asks.
* **D. What is the host for an image?** `host` is keyed `(realm, stable_id)` and a container is a host with `kind: container`; an image digest is not a running container. Needs a ruling on a `realm` for an image
  digest before `INSTALLS_PACKAGE` is drawn.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-16-1 | One document | Proposed | The crypto section is merged into the primary CycloneDX document during the single derivation; no second CBOM document and no second predicate type exists. | Decision 3. |
| req-cicd-sbom-16-2 | Findings land on an owner | Proposed | Every `crypto_bom` finding for the scanned digest appears in the document as `tap:crypto:<n>:*` properties on its owning component; an unowned finding becomes a `file` component with the same properties and is counted in the coverage statement. None is dropped. | Decision 2. |
| req-cicd-sbom-16-3 | Closed disposition vocabulary | Proposed | `tap:crypto:<n>:boundary` is exactly one of the five `Boundary` values; a finding without one, or with another, fails generation. | A document may not launder an unclassified provider. |
| req-cicd-sbom-16-4 | Sentinel in the document | Proposed | Generation fails if the scan read no binaries, or did not see `openssl-system` and the declared FIPS provider. | The anti-fail-open sentinel of `req-fips-crypto-bom`, carried to the document. |
| req-cicd-sbom-16-5 | Coverage states the limits | Proposed | `tap:coverage` states that providers are covered and that algorithms, protocols, certificates and key material are not, until a later requirement adds them. | Known-unknowns discipline, `req-cicd-sbom-11`. |
| req-cicd-sbom-16-6 | Schema matches the emitted version | Proposed | The vendored CycloneDX schema used for validation has the same `specVersion` as the emitted document before any `cryptographic-asset` component is emitted. | Today a 1.7 document is validated against the 1.6 schema. |
| req-cicd-sbom-16-7 | Scan of the exported digest | Proposed | The scan reads the exported filesystem of the verified per-arch digest through explicit roots, in first-party code; the image never scans itself. | `req-fips-crypto-bom-3`; tap#507 token separation unchanged. |
| req-cicd-sbom-16-8 | No key material | Proposed | The document carries no `related-crypto-material` `value`, and no key, secret or token bytes under any `tap:crypto:*` property. | Mirrors the computing-core-tap `crypto_provider` no-key-material criterion. |
| req-cicd-sbom-16-9 | Verify before parse | Proposed | Ingestion parses only the `statement.predicate` returned by a successful `gh attestation verify --predicate-type https://cyclonedx.org/bom` for the document's subject digest, and records the digest and the verification outcome on the SBOM node. A failed or unobservable verification ingests nothing. | Three states as `-4`: verified, missing, not observable. |
| req-cicd-sbom-16-10 | One generic parser | Proposed | The CBOM mapping is a step of the same CycloneDX parser that maps packages, libraries and source packages; there is no second parser. | Decision 5. |
| req-cicd-sbom-16-11 | Provider identity converges | Proposed | A parsed finding keys on `(scope, artifact, provider)` with the registry's own strings, so it updates an existing `crypto_provider` node and never creates a second. | Decision 5. |
| req-cicd-sbom-16-12 | Source packages from the SBOM origin | Proposed | `source_package` nodes are derived from `syft:metadata:originPackage` (or `name` where equal), with the version taken from the members' shared version; a disagreeing member fails the parse. No type or edge changes. | Decision 5; observed 101/101, 69 origins, 11 multi-binary. |

### Vulnerability Evidence from SBOMs - Overview and Decision Ledger
----

This group of requirements (`req-cicd-sbom-17` to `req-cicd-sbom-30`) turns the attested image SBOM into the thing that drives vulnerability status on the grid and, next, vulnerability detection and
response (VDR) processing. Maintainer direction (George, 2026-10-15, relayed by the support session): stay on CycloneDX; work with teams to generate standardized CycloneDX SBOMs on their side; ingest
them; use them to drive vulnerability status. Nothing here is built; every requirement is `Proposed`.

**The flow, in plain steps.** (1) A team's CI calls ONE reusable workflow TAP ships, so no team writes its own. (2) The workflow builds the SBOM with Syft (CycloneDX 1.7). (3) It scans that SBOM with a
vulnerability scanner, and scans the image as a cross-check. (4) It merges the scanner outputs into one list, one entry per vulnerability and component, saying which scanner saw it. (5) It adds facts from
public records (CVSS, CWE, CISA's SSVC assessment, CISA's Known Exploited Vulnerabilities flag), each stamped with where and when it came from. (6) It validates the document and fails the run if it is
malformed. (7) It signs the result as an attestation bound to the image digest. (8) Before an image is promoted, a gate checks the CURRENT KEV catalog and blocks a KEV-listed image. (9) TAP ingests: it
verifies the attestation first, then parses only the verified content onto the grid as packages, libraries, source packages, vulnerabilities, findings, scan runs and scanners. (10) A dashboard counts
vulnerabilities over the images that are currently deployed.

**Method key used throughout.** `read` = I opened the file or page; `ran` = I executed the command and observed the output (2026-10-15, in the stat-card worktree with throwaway containers); `inferred` =
reasoned, not observed. Anything not observed is marked NOT OBSERVED.

#### Decision ledger

| Id | Question | State | Where |
| --- | --- | --- | --- |
| SV-1 | One merged document, or a separate vulnerability document per digest? | Decided: one merged document, revised through CycloneDX serial and version; all revisions kept (revisit); the signature means CI ran the named tools | `req-cicd-sbom-20` |
| SV-2 | Scan the SBOM, the image, or both? | Decided: both | `req-cicd-sbom-19` |
| SV-3 | Which plugin owns the SBOM node and parser? | Decided: `computing_core` | `req-cicd-sbom-24` |
| SV-4 | Do the `dependsOn` links become edges? | Decided: yes for now (provisional) | `req-cicd-sbom-28` |
| SV-5 | Who owns the deploy gate and what does it block on? | Decided: block promotion on KEV; the waiver path is unruled | `req-cicd-sbom-21` |
| SV-6 | How are alert-derived and SBOM-derived findings kept from double counting? | Decided: keep both and correlate; retire alert component findings later | `req-cicd-sbom-27` |
| SV-7 | Dependabot: fetch in CI, or leave it to the existing collector? | Decided: fetch in CI | `req-cicd-sbom-23` |
| SV-8 | Whose attestation signers does TAP trust? | Decided: default-deny list, one signer to start | `req-cicd-sbom-22` |
| SV-9 | The Renovate gap for the scanner pins | Decided: add managers (build later) | `req-cicd-sbom-29` |
| SV-10 | CI side: is a thin SBOM refused, or recorded and flagged? | Decided (George 2026-10-15): fail first; the run fails on a `thin` verdict. Whether a caller may opt in to recording `thin` instead is not ruled and is not specified | `req-cicd-sbom-32-6` |
| SV-11 | CI side: does every scan publish a revision, or only a scan whose facts changed? | Decided (George 2026-10-15): a revision is published only when the facts changed; REVISIT once Issue# 322 - tap and Issue# 323 - tap (epic Issue# 886 - tap) are in place, when publishing every scan becomes possible and the unused grid state can carry the scan time | `req-cicd-sbom-20-11` |

All nine were ruled by George on 2026-10-15 through the support session, which relayed them to the coordinating session; the relayed text is the only record of the rulings at this time (SV-8 was
confirmed a second time). Where a requirement fills in detail the ruling did not state (the waiver path, retention numbers, the edge name, the correlation key), that detail is this spec's proposal and
says so.

### Vulnerability Evidence Workflow
----
RID: `req-cicd-sbom-17`

Status: `Proposed`

TAP ships ONE reusable GitHub Actions workflow, called from each team's own repository, that produces signed vulnerability evidence for an image digest. Teams supply inputs (image reference by digest,
supplemental manifest if any); they do not write scanner steps. This is the same declare-vs-decide pattern as `req-cicd-sbom-10`: the author's pipeline declares, TAP verifies and composes. It is the
generalisation of the existing `sbom` and `attest-sbom` jobs of the publish pipeline (`req-cicd-sbom-1`, `-4`, `-6`, read) from "two TAP images" to "any team image".

Stages, in order, each fail-closed unless marked:

| # | Stage | Requirement | Method |
| --- | --- | --- | --- |
| 1 | Generate | Pinned Syft, one derivation per digest, CycloneDX 1.7 primary (`req-cicd-sbom-1`, `-6`). SPDX is emitted from the same scan; Syft v1.54.1 emits SPDX 3.0.1 (`-o spdx-json@3.0`, document `@context` is the 3.0.1 context) | ran (v1.54.1 on a one-file directory: CycloneDX `specVersion` 1.7 and SPDX 3.0.1 context); the current pin is v1.51.0 (read, `scripts/sbom/generate.py`), which emits 1.7 (read, the real documents) |
| 1b | Check completeness | The field check of `req-cicd-sbom-32` over the generated (or caller-supplied) document, before any scanner reads it | proposed; fields measured on the real document (ran, jq) |
| 2 | Scan the SBOM | Grype (see `req-cicd-sbom-19`) reads the SBOM as the component record | ran |
| 3 | Scan the image | A cross-check by a second scanner, difference-reporting (`req-cicd-sbom-19`) | read (existing Trivy lane) |
| 4 | Merge (as the next revision of the SAME document, `req-cicd-sbom-20`) | `req-cicd-sbom-18` | ran |
| 5 | Enrich | `req-cicd-sbom-18` | ran |
| 6 | Validate | Schema validation and the minimum-elements checks of `req-cicd-sbom-11` over the final document, not only the Syft output | read |
| 7 | Attest | `actions/attest`, subject = the per-arch digest, signed in a first-party-only job (`req-cicd-sbom-4`, tap#507); the signer identity is the one `req-cicd-sbom-22` trusts | read |
| 8 | Gate | `req-cicd-sbom-21`, at promotion rather than at build | inferred |

A rescan mode is part of the same workflow: given a digest, it fetches and verifies the already-published SBOM attestation (`req-cicd-sbom-24`) and uses that document, never a regenerated one, as its input; it rescans with the current scanner database and produces the next revision of the same document (`req-cicd-sbom-20`). Rescans are what keep "current" current (`req-cicd-sbom-26`) and are what a scheduled caller invokes; the workflow does not schedule itself.

**Scanner capability facts the stage list depends on (ran, 2026-10-15).** Grype v0.120.1 read the real tap-web arm64 CycloneDX 1.7 SBOM and emitted CycloneDX 1.7 plus its native JSON. Trivy 0.75.0
and 0.76.0 both read the same 1.7 document and produced identical vulnerability sets (24 distinct ids, 24 of 24 also matched by Grype). Trivy is not required to read SPDX 3 and cannot (per the task
brief; NOT OBSERVED by this author). Grype reading SPDX 3.0.1 is the support session's claim (a file `grype120-spdx3.json` exists in the support scratchpad; NOT re-run here).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-17-1 | One reusable workflow | Proposed | Teams obtain vulnerability evidence by calling one TAP-owned reusable workflow; a team-authored scanner step is not the supported path. | |
| req-cicd-sbom-17-2 | Digest-threaded | Proposed | Every stage addresses `ref@digest`; no stage resolves a mutable tag (`req-cicd-supply-chain-provenance-1`). | |
| req-cicd-sbom-17-3 | Fail closed per stage | Proposed | A failed, skipped or unobservable stage 1, 2, 4, 5, 6 or 7 fails the run; stage 3 and the Dependabot intake record a visible not-observed marker instead (`req-cicd-sbom-19-3`, `req-cicd-sbom-23-2`). | Three states: done, failed, not observed. |
| req-cicd-sbom-17-4 | Rescan mode | Proposed | The workflow can rescan a digest from its verified, already-published SBOM without regenerating it. | |
| req-cicd-sbom-17-5 | Scanners are unsigned | Proposed | Scanner steps run in a read-only unsigned job; only a first-party job that merges and validates holds the signing token (`req-cicd-sbom-20-6`). | |
| req-cicd-sbom-17-6 | Completeness stage | Proposed | Stage 1b runs before any scanner and fails the run on a `thin` verdict (`req-cicd-sbom-32-6`); a check that could not run fails the run. | Added by the CI-side spec (tap#1044). |
| req-cicd-sbom-17-7 | Two jobs, named | Proposed | The workflow has exactly two jobs. `scan` is unsigned and read-only (`contents`, `packages`, `attestations` read): it verifies the input, runs the completeness check, Grype and the network fetches of `req-cicd-sbom-18-8`, and merges and enriches into the next revision. `seal` holds `id-token` and `attestations` and runs first-party steps only (`actions/*`, no checkout, no scanner, no third-party action): it re-binds the document to the SHA-256, serial and version the `scan` job recorded, checks the completeness verdict, and attests. | Decided with George 2026-10-16 (Q8): the merge runs in the read-only job, the pattern of `plugin-release-sbom.yml`, so the signing job stays minimal. Residual: the split protects the signing token, not the content. Refines `-17-5`; changes the earlier text, which put the merge in `seal`. |
| req-cicd-sbom-17-8 | Inputs and outputs | Proposed | The workflow takes the image path and a `sha256:` digest (both matched against strict patterns before use; a tag is refused), and a boolean `attest` (default true; false stops after the merge and signs nothing). It outputs `result` (`changed` or `unchanged`) and the new `revision`. Grype is pinned by image digest. | Implemented in `.github/workflows/sbom-vulnerability-evidence.yml`; the pin's Renovate manager is `-29`. |

### Merge and Enrichment
----
RID: `req-cicd-sbom-18`

Status: `Proposed`

**Merge rules** (the scanners disagree on identifiers, so the merge is where correctness is made):

1. **Remap `bom-ref` by purl.** Grype regenerates every `bom-ref`; the original references do not survive. Measured: of 191 source `bom-ref`s, **1** appears unchanged in Grype's CycloneDX output, versus **191
   of 191** in Trivy's (ran, arm64 document). Every scanner output is therefore joined to the SBOM by the component's purl (and by name+version for the one component without a purl, the `wolfi`
   operating-system entry), never by `bom-ref`. All 182 distinct purls of the SBOM were present in Grype's output; Trivy's output held 179 of them plus 3 not in the source (ran; the 3 not investigated).
2. **Attribute per entry.** Each merged vulnerability entry carries the scanner that reported it in the entry's own `tools` field (present in the vendored 1.6 schema, `definitions.vulnerability`, read).
   An entry reported by two scanners lists both.
3. **Dedupe by vulnerability and component.** One entry per (canonical vulnerability id, component purl). The canonical id is the CVE id when any alias is a CVE, otherwise the GHSA id (the same rule
   as the `compliance_vulnerability` key, read). All other ids are kept as aliases.
4. **Aliases must come from the scanner's native output.** Grype's CycloneDX output carries one id per entry (ran: 148 entries, `references` has exactly one element in all 148) and does not list the
   CVE alias of a GHSA entry; Grype's native JSON does (`relatedVulnerabilities`: 73 of 148 matches carry one; 46 matches are GHSA-identified and 19 of those name a CVE; ran). The workflow therefore
   runs Grype once and emits BOTH outputs from the same database state (`-o cyclonedx-json=... -o json=...`, ran in one invocation), merging aliases from the native JSON.
5. **Keep every rating, with its source.** Ratings are not collapsed: Trivy emits one rating per vendor (ran: redhat, ghsa, nvd, azure, ubuntu, bitnami, amazon on the arm64 document); Grype emits CVSS
   and a FIRST EPSS rating (ran: 121 EPSS ratings on 148 entries).
6. **Fix versions** are kept per entry: Grype's native JSON states `fix.state` (ran: 78 fixed, 69 unknown, 1 not-fixed of 148) and CycloneDX carries `affects[].versions` and `recommendation`.

**Enrichment rules** (done in CI so the attested document carries facts with provenance; every enrichment is stamped with its source, retrieval time and, where it has one, the source's version):

| Fact | Source | Carried as | Method |
| --- | --- | --- | --- |
| CVSS, CWE | the CVE record (CVE Program JSON 5) | `ratings[]` with `source`, `method`, `vector`; `cwes[]` | ran (CVE-2021-44228 record fetched from `cveawg.mitre.org`) |
| SSVC (Exploitation, Automatable, Technical Impact) | the CISA-ADP container of the CVE record: `containers.adp[]` with `providerMetadata.shortName` `CISA-ADP`, `metrics[].other.type` = `ssvc`, content version `2.0.3`, a timestamp | a rating with `method: SSVC`, the three options in `vector` (`Exploitation:active/Automatable:yes/Technical Impact:total`) and the assessment version and timestamp in `justification`; the same facts as entry properties `tap:ssvc:exploitation`, `tap:ssvc:automatable`, `tap:ssvc:technical-impact`, `tap:ssvc:assessed-at`, `tap:ssvc:version` so a parser need not read a vector string; `SSVC` is a member of the CycloneDX `scoreMethod` enum (read, vendored schema) | ran (record); the merged shape passes the vendored 1.6 schema on the real tap-web document (ran, `scripts/sbom/merge_enrich.py`) |
| KEV | CISA's catalog JSON (`known_exploited_vulnerabilities.json`) | a rating with `method: other`, `source.name: CISA KEV Catalog`, `justification: Listed in CISA KEV`, plus `tap:kev:catalog-version`, `tap:kev:date-released`, `tap:kev:fetched-at`, `tap:kev:date-added`, `tap:kev:due-date`, `tap:kev:required-action`, `tap:kev:ransomware-use` (the catalog's `knownRansomwareCampaignUse`, kept verbatim, e.g. `known`) and `tap:kev:matched-id` (the alias the catalog matched, always a CVE id) properties, on the ONE merged entry of the canonical id (`-18-7`) | ran: the catalog carries `catalogVersion` (`2026.10.15`), `dateReleased`, `count` (1746); Grype's native `knownExploited[]` entry for CVE-2021-44228 carries `dateAdded`, `dueDate` (`2021-12-24`), `requiredAction` and `knownRansomwareCampaignUse` (`known`) (read, `jq` over the support session's `kevspike/out/json.json`) |
| EPSS | taken from Grype's FIRST rating as emitted; the score date comes from Grype's native JSON when it carries one | rating, `source.name: FIRST`, plus `tap:epss:percentile` and `tap:epss:date` from the native JSON | ran (rating); read (`jq`, same output file): the native JSON carries `epss:[{cve, epss, percentile, date}]` (CVE-2021-44228: 0.99999, percentile 1, date 2026-10-14) |

KEV has no standard CycloneDX field. The convention TAP adopts is Grype's: Grype emits exactly that rating shape when a KEV match exists (ran: a probe SBOM of `log4j-core@2.14.1`, grype v0.120.1, gave the entry
`GHSA-jfh8-c2jp-5v3q` with a `CISA KEV Catalog` rating, score 1, justification `Listed in CISA KEV`, and an EPSS rating of 0.99999). Two cautions from the same probe: Grype named the vulnerability by its GHSA id,
not by CVE-2021-44228, so a KEV lookup MUST be done over the vulnerability's whole alias set, never its primary id alone; and Trivy has no native KEV or EPSS (the task brief cites aquasecurity/trivy#2558; NOT
re-read here) and returned no entries for the maven probe (cause not investigated). The CISA-ADP container also carries a `kev` metric (ran); the catalog JSON remains the source because the gate needs the catalog's own version stamp.

The 2026-10-15 tap-web arm64 measurement found **no KEV-listed vulnerability** among the 65 distinct ids (41 CVEs) Grype reported (ran: intersection with catalog 2026.10.15 is empty).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-18-1 | Join by purl | Proposed | No scanner output is joined to the SBOM by `bom-ref`; the join key is purl (name+version for a component without one). | Grype: 1 of 191 `bom-ref`s survive. |
| req-cicd-sbom-18-2 | Per-entry attribution | Proposed | Every merged entry names each reporting scanner and its version in `tools`. | |
| req-cicd-sbom-18-3 | One entry per vulnerability and component | Proposed | The merged document has at most one entry per (canonical vulnerability id, component); GHSA and CVE aliases are kept. | |
| req-cicd-sbom-18-4 | Provenance on every enrichment | Proposed | Each CVSS, SSVC and KEV fact carries its source, retrieval time and source version; a fact with no recorded source is refused. | |
| req-cicd-sbom-18-5 | KEV over aliases | Proposed | A KEV match is evaluated over every alias of a vulnerability; the catalog version, release time and fetch time are stamped into the document. | |
| req-cicd-sbom-18-6 | Not read is not false | Proposed | If the KEV catalog or a CVE record could not be read, the fact is recorded as not observed, never as "not KEV" or "no score". | `kev: null` versus `false`, as the vulnerability node's convention. |
| req-cicd-sbom-18-7 | KEV lands on the canonical entry | Proposed | When Grype names a finding by GHSA and the catalog matches one of its CVE aliases, the KEV rating and `tap:kev:*` properties are written on the merged entry of the canonical id (the CVE, per rule 3), never on a separate GHSA entry; `tap:kev:matched-id` names the CVE. | Read from the existing probe outputs (log4j-core 2.14.1, Grype v0.120.1, support's `kevspike/out`, `jq`): in the CycloneDX output the KEV rating (`source.name` `CISA KEV Catalog`, score 1) sits on the entry named `GHSA-jfh8-c2jp-5v3q`, with no CVE id and no date anywhere in that entry; the CVE (`CVE-2021-44228`) and `dateAdded` appear only in the native JSON (`knownExploited[]`, `relatedVulnerabilities[]`). So the CVE for `tap:kev:matched-id` MUST come from the native JSON. The merged document itself is NOT OBSERVED until the merge is built. |
| req-cicd-sbom-18-8 | Fetch unsigned, join first-party | Proposed | The KEV catalog and CVE records are fetched in the `scan` job and travel as hash-held artifacts; the `seal` job parses and joins them offline in first-party code, and records each source's SHA-256 in the document. | The signing job needs no network beyond Sigstore. |
| req-cicd-sbom-18-9 | Affects point at the SBOM's own refs | Proposed | Every merged entry's `affects[].ref` is the `bom-ref` of the revision-1 component with the same purl, never a `bom-ref` taken from a scanner output. | Grype regenerates refs (`-18-1`). |
| req-cicd-sbom-18-10 | Every revision re-evaluates | Proposed | Enrichment facts are recomputed from the sources fetched for THAT scan; a fact is never copied forward from the previous revision, so a KEV flip, an SSVC change or a retracted match appears in the next revision. | A copied-forward fact would make the stamp lie about its date. |
| req-cicd-sbom-18-11 | No lookup on the consuming side | Proposed | Every enrichment fact the grid or the deploy-gate reporting needs (KEV, EPSS, SSVC, CVSS, CWE) is read from the verified document; an instance makes no outbound lookup to obtain it. | George 2026-10-15: CI does the lookups. The deploy gate's fresh catalog fetch (`-21`) is a gate action, not an instance lookup. |
| req-cicd-sbom-18-12 | Scanner KEV is never dropped | Proposed | Every entry carries `tap:kev:listed` as `true`, `false` or `not-observed`. A vulnerability the fetched catalog does not list but the scanner's own data does is `true` with `tap:kev:source` = `grype`; one the catalog lists is `true` with `tap:kev:source` = `catalog`. | A stale fetched catalog must not clear what the scanner database already flags. Implemented in `scripts/sbom/merge_enrich.py`. |
| req-cicd-sbom-18-13 | Merge exit codes | Proposed | The merge exits 0 and writes the next revision when facts changed, 3 and writes nothing when they did not (`-20-11`), and 2 when a required input is missing or the scanner names a component the SBOM does not contain. | Stage 4 fails closed (`-17-3`); an unreadable KEV catalog or CVE record is `not-observed`, not a failure (`-18-6`), which is how the two rules are reconciled. |
| req-cicd-sbom-18-14 | Published, title, description and record URLs | Proposed | Each vulnerability entry carries `published` (the CVE record's `datePublished`, else the GitHub advisory's `published_at`), `updated`, a `description` (the scanner's own when it gave one, else the CVE record's English description, else the advisory's), a `tap:title` property (the record's `title`, else the advisory's `summary`; CycloneDX has no title field), and `advisories[]` of `{title, url}`: `CVE Record` at `https://www.cve.org/CVERecord?id=<CVE>` and `GitHub Advisory` at the advisory page. | Asked for by the grid session for the playground vulnerability pages (Published column, severity by age, descriptions). Ran 2026-10-19: a CVE record carries `datePublished`, `title` and `descriptions`; `GET /advisories/<GHSA>` carries `published_at`, `summary`, `description`, `html_url`. |
| req-cicd-sbom-18-15 | GitHub advisories come from the scan job | Proposed | The GHSA ids in the scanner output are fetched from `https://api.github.com/advisories/<id>` in the `scan` job with the workflow token and no new secret, and join the merge offline like the CVE records (`-18-8`); an advisory that could not be read is `tap:ghsa:status` = `not-observed`, and the document records `tap:ghsa-advisories:status` and the source's SHA-256. | Public data; the token only raises the rate limit (60 an hour unauthenticated, ran). Identifiers are matched against the GHSA pattern before they reach a URL. |
| req-cicd-sbom-18-16 | A touched record does not publish | Proposed | `updated` is not a fact for the change test of `-20-11`: a record whose `dateUpdated` moved with nothing else changing publishes nothing; a changed `published`, title, description or advisory does. | CVE records are touched often; EPSS is excluded for the same reason. |

### Scan Coverage - SBOM Scan and Image Cross-Check
----
RID: `req-cicd-sbom-19`

Status: `Proposed`

**Decided (SV-2, George 2026-10-15): scan both.** The SBOM scan is the component record: it is what TAP ingests and counts. The image scan is a cross-check that reports differences; it does not feed
counts by itself.

Why both are needed, from the data (ran unless stated): the SBOM deliberately excludes the wheel-cache seed (`req-cicd-sbom-2`), yet an image scan reads it. Of the 400 code-scanning alerts in
the local grid export (read from the stat-card scratchpad `code-scanning.grift.json`, dated 2026-10-14), 108 are located under `opt/uv-cache-seed` (106 fixed, 2 open).
The converse also holds: the SBOM scan finds apk packages and the out-of-band FIPS provider (6 `pkg:generic` matches on arm64) that an image scan may attribute differently. Neither alone is complete.

The cross-check output is a `tap:scan-differences` section of the document: findings reported by one scan and not the other, each with a reason class where one is known (`path-excluded-by-req-cicd-sbom-2`,
`scanner-database-difference`, `unknown`). Differences are information, not failures, unless a KEV-listed vulnerability appears only in the image scan (then the gate treats it as present,
`req-cicd-sbom-21`).

**Scanner roles.** Grype is the required SBOM scanner (it matches on purl and on CPE; see the grype-nightly lane header, read, for why a CPE-only component such as the self-built FIPS provider is invisible to
Trivy). Trivy at or above the pin of core PR #1036 (v0.75.0) is the image cross-check and MAY also scan the SBOM. On the same arm64 SBOM Grype reported 148 matches (49 distinct ids on 123 apk, 19 pypi, 6 generic
components) and Trivy 24 (all 24 also reported by Grype; 5 apk, 19 pypi). Which of Grype's 124 additional apk and generic matches are true positives is NOT OBSERVED.

**Why two Trivy counts exist (the 24 versus 7 question).** Trivy 0.75.0 and 0.76.0 return the same 24 vulnerabilities on the d86ebb77... arm64 SBOM (ran, identical id sets). The "7" is the result on a
different document: the support session's `trivy76-cdx.json` is a scan of the SBOM for digest `sha256:a9149a88...` (the later `:latest` arm64 image), and running both Trivy versions on that other SBOM
gives 7 (ran). The versions do not differ; the images do.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-19-1 | SBOM scan is the record | Proposed | Counts and ingestion use the SBOM-scan result; the image scan never adds findings to counts on its own. | |
| req-cicd-sbom-19-2 | Differences are reported | Proposed | Every finding present in exactly one of the two scans appears in `tap:scan-differences` with a reason class. | |
| req-cicd-sbom-19-3 | Missing cross-check is visible | Proposed | If the image scan could not run, the document records `tap:image-scan: not-observed` with the reason; it is never an empty difference list. | |
| req-cicd-sbom-19-4 | Scanner pins are recorded | Proposed | The scanner name, version and database build time of each scan are recorded in the document. | Grype's native output carries the database build time (ran: `built` 2026-10-15T06:30:36Z, schema v6.1.10). |

### Document Revisions - One Merged Document
----
RID: `req-cicd-sbom-20`

Status: `Proposed`

**Decided (SV-1, George 2026-10-15): one merged document.** The unit TAP ingests is a single CycloneDX document holding components, vulnerabilities and scanner information together: one source of truth,
processed on TAP's side ("derive a fact once"); separate point updates are an optimization that does not generalize. An image digest is immutable, so its component list is fixed, but its
vulnerabilities are not (new CVEs, KEV flips and SSVC assessments arrive daily, and a database correction can retract one), so the document is revised over time and each revision is true as of its timestamp.

**The revision mechanism (proposed by the support session; evaluated here and ADOPTED, with the rules below).** CycloneDX has its own lineage. The vendored 1.6 schema (read,
`scripts/sbom/schemas/bom-1.6.schema.json`, `properties.serialNumber` and `properties.version`) says: every BOM generated "SHOULD have a unique serial number, even if the contents of the BOM have not
changed over time"; "Whenever an existing BOM is modified, either manually or through automated processes, the version of the BOM SHOULD be incremented by 1"; and "When a system is presented with multiple BOMs
with identical serial numbers, the system SHOULD use the most recent version of the BOM". Applied:

1. The build-time SBOM is **revision 1**: components only (version 1, as Syft writes it, read), signed once, preserved forever.
2. Each scan produces the **next revision of the SAME `serialNumber`**: `version` incremented by 1, carrying the components unchanged plus that scan's vulnerabilities and scanner information, attested again.
3. **Current = the highest `version` for a serial number, per subject digest.** Older revisions are history and are never deleted from the grid.
4. Syft generates a fresh `serialNumber` on every run (read: the arm64 and amd64 documents differ; ran: Grype's own CycloneDX output carries a third, unrelated serial, `version` 1), so the merge step MUST carry the
   ORIGINAL SBOM's `serialNumber` forward and MUST NOT take the serial from any scanner output. A scan input is the already-published, verified SBOM of the digest (`req-cicd-sbom-17` rescan mode), never a regenerated one.
5. **Identity for idempotent ingest stays the content digest** (`req-cicd-sbom-25`), not serial and version: two documents can legitimately share serial and version if two scans race to revise the same revision N.
   Both are ingested as distinct documents; "current" breaks the tie by the later signature time (`req-cicd-sbom-22`), then by content digest, deterministically.
6. **Why the schema's wording is compatible.** The "unique serial number even if contents have not changed" sentence governs separately generated BOMs; a revision of a BOM is the schema's own "existing BOM is
   modified" case. Where a consumer meets two revisions it uses the later, as the schema says.

**Questions the mechanism raises, answered.**

* **Retention - Decided (George 2026-10-15): keep ALL revisions; no retention policy for now** ("we're not storing the files in the db anymore, so who cares?"). **To REVISIT when volume matters.** The
  volume is about 1 MB per revision per architecture per day (ran: components 0.62 MB, Grype's `vulnerabilities` section 0.29 MB and Trivy's 0.05 MB on the arm64 document; one revision a day for a year is about 365 MB
  per architecture per image). Revisions live in the file store of tap#1035, never in the database. **The files are outside the database, so the backup contract decides whether they survive a restore.**
  `spec-tap-backup.md` (read) captures a database dump, boot profile, plugins and logs; its manifest always declares a `media` component that is `none-exists` today, and says "a future upload feature must
  change this entry or `verify` fails" (read, the manifest section). The stored SBOM files are exactly such a feature, so until the file store declares itself in the backup manifest, a restore keeps
  the SBOM nodes and their file references but NOT the files, and a reference then points at nothing. Where the files live and what the backup does with them is an open question of tap#1035 (read: "where files
  live (a volume, with what backup behaviour: `spec-tap-backup.md` is the existing contract)"); this spec does not answer it, and `req-cicd-sbom-20-8` requires that it be answered before the file store is
  relied on.
* **What the signature on the merged blob means - Decided (George 2026-10-15): CI is trusted.** ("If you can't trust CI who can you trust?") The signed document carries first-party component facts (what Syft saw
  in the image) and scanner claims (what Grype and Trivy matched), and the signature may be read as: **the named CI job ran the named tools at the named versions and recorded their output**. Nothing more.
  It does not make a scanner right: Trivy itself was compromised in March (CVE-2026-33634, as relayed by the maintainer; NOT re-read here), which is why tool pins are by immutable release and commit
  (`req-cicd-sbom-29`; the existing `renovate.json5` rule for `trivy-action` was read and cites the same incident). Per-entry `tools` attribution (`req-cicd-sbom-18`) is kept because the page needs a scanner column and
  for traceability, **not as a trust hedge**. TAP's trust check is by signer, as ruled (`req-cicd-sbom-22`).
* **Separation of duties stays.** The merge-and-attest job is first-party and keeps the existing split of `publish-images.yml` (read: the `sbom` job holds a read-only token and runs generation and third-party
  code; `attest-sbom` is "FIRST-PARTY STEPS ONLY" and holds `id-token`/`attestations`). Scanners run in an UNSIGNED job with a read-only token; their raw outputs travel as integrity-held workflow artifacts to
  a first-party job that merges, enriches, validates and signs. No scanner and no third-party action shares the signing token (tap#507 unchanged).
* **The release gate.** `req-cicd-sbom-4` requires at least one verifying SBOM attestation per digest before a version tag; with several revisions each is an attestation of the same predicate type, so that predicate
  still holds ("at least one verifying bundle"); a consumer wanting the newest selects the highest `version`.

**Considered and rejected: a separate vulnerability document per digest**, bound to an immutable SBOM by serial and digest. It would keep the SBOM hash-stable and match the two cadences, but it needs two documents,
a second predicate type (the URI for a vulnerability-only CycloneDX document is NOT OBSERVED; only `https://cyclonedx.org/bom` and the SPDX URI have been seen on real attestations), a binding to verify on ingest (a new
failure class), and a second source of truth to keep consistent. George chose one document so each fact is derived and held once.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-20-1 | One merged document | Proposed | The ingested unit is one CycloneDX document with components, vulnerabilities and scanner information. | |
| req-cicd-sbom-20-2 | Revision 1 is the build SBOM | Proposed | The build-time SBOM, components only, is revision 1, signed once and never altered or deleted. | |
| req-cicd-sbom-20-3 | A scan revises, it does not replace | Proposed | A scan emits `version` + 1 of the SAME `serialNumber`, attested again; the serial is carried from the verified input, never from a scanner. | |
| req-cicd-sbom-20-4 | Current is the highest version | Proposed | Per subject digest and serial, the highest `version` is current; ties break by later signature time, then content digest; older revisions are never deleted from the grid. | |
| req-cicd-sbom-20-5 | Attribution and what the signature covers | Proposed | Every vulnerability entry carries `tools` (for the scanner column and traceability); the signature is documented as covering that the named CI job ran the named tools at the named versions and recorded their output, and not that a scanner is right. | George: CI is trusted. |
| req-cicd-sbom-20-6 | Separation of duties | Proposed | Scanners run in an unsigned read-only job; a first-party job merges, validates and signs. | |
| req-cicd-sbom-20-7 | Every revision is kept | Proposed | Every revision file is kept in the tap#1035 file store, never in the database; no retention policy exists for now. | Decided; REVISIT when volume matters (about 1 MB per revision per architecture per day). |
| req-cicd-sbom-20-8 | Restore keeps the files | Proposed | Before the file store is relied on, the backup manifest declares it, so a restore brings back the files its SBOM nodes refer to or states that they are absent. | Open question of tap#1035; `spec-tap-backup.md` `media` component. |
| req-cicd-sbom-20-9 | Revision chain is checkable | Proposed | Every revision after the first carries `tap:revision:previous-content-digest` (SHA-256 of the revision it was made from) and `tap:revision:input-attestation` (the digest of the verified attestation it read); a consumer can then detect a missing or skipped revision. | CI-side proposal; serial and version alone cannot show a gap. |
| req-cicd-sbom-20-10 | Rescan reads the highest verified revision | Proposed | A rescan takes as input the highest `version` of the serial whose attestation verifies against the trust list; it never starts from a lower revision and never from a regenerated SBOM. If two highest revisions tie, it uses the tie-break of `-20-4`. | |
| req-cicd-sbom-20-11 | Publish only on change | Proposed | A scan publishes the next revision only when the document's facts differ from the highest verified revision: the components, the set of vulnerability entries (canonical id, affected component, aliases, fix versions), their CVSS, SSVC and KEV facts, and `tap:completeness`. Timestamps, scanner database build times, source fetch times and the KEV catalog version stamp are NOT facts for this test, and neither are EPSS score and percentile, which move daily; a changed EPSS alone does not publish. A scan that publishes nothing still leaves its run log and job summary naming the digest, the revision compared and the verdict `unchanged`. | Decided (SV-11, George): the ingest re-writes finding nodes, and until Issue# 322 - tap ships each unchanged re-write adds history. The EPSS exclusion is this spec's proposal. REVISIT when #322 and #323 are in place (note on Issue# 886 - tap): publish every scan then. Cost: the grid cannot show "scanned clean as of T" on unchanged days. |
| req-cicd-sbom-20-12 | CI emits the ingest keys | Proposed | The document and attestation carry what the grid keys on: a `serialNumber` equal to revision 1's, a `version` of the previous plus 1, and an attestation subject equal to the per-arch image digest. The content digest of a revision is the SHA-256 over the exact bytes of the `predicate` value inside the signed DSSE payload, never over a re-serialization; the rescan stages those bytes untouched and records that digest in `tap:revision:previous-content-digest` of the next revision. | The grid fields `serial_number`, `revision`, `subject_digest`, `content_digest` come from computing-core's spec; `signer` and `verified` are produced by the consumer's verification. Rule agreed with the grid session 2026-10-16: the verified payload bytes, because nothing needs re-serializing. Ran: the predicate cut from the real tap-web payload is 499,619 bytes. |

### Deploy Gate
----
RID: `req-cicd-sbom-21`

Status: `Proposed`

**Decided (SV-5, George 2026-10-15): the gate BLOCKS PROMOTION of an image that has a KEV-listed vulnerability** ("block on images with KEV"), re-checked against the CURRENT catalog at promotion. The
ownership, mechanics and the waiver path below are this spec's proposal for that ruling; the waiver path is UNRULED.

* **Where it runs.** In the promotion job, the step that moves an image toward consumers. For TAP's own images that is the existing release gate (`retag` before a version tag, and `promote-latest`, `req-cicd-sbom-4`,
  read). For team images it is a `gate` mode of the reusable workflow (`req-cicd-sbom-17`) that the team's promotion job must call before it moves a tag. The owner of the gate step is TAP (the workflow); the owner of
  the decision to call it is the team's promotion job. A team that does not call it is not gated; making the call mandatory is a platform control outside this spec.
* **What it reads.** (1) the verified attestation for the digest, which names the components and carries a KEV stamp as of build time; (2) a FRESH fetch of the KEV catalog at promotion; (3) a fresh scan
  of the verified SBOM with the scanner's current database (`req-cicd-sbom-17` rescan mode). The attested KEV stamp is advisory: a vulnerability that became KEV-listed after the build is not
  in it, and one the build-time database did not yet know is not in the build-time list. The decision uses (2) applied to the findings of (3) over every alias, plus any KEV-listed vulnerability that
  appears only in the image cross-check (`req-cicd-sbom-19`).
* **Fetch failure is a block.** If the catalog cannot be fetched, does not parse, lacks `catalogVersion` or `dateReleased`, or is empty, or the scan cannot complete, the gate fails closed (three states:
  clear, blocked, not observable; the last blocks).
* **Waiver (UNRULED, proposal).** A waiver is a committed data record naming the vulnerability id, the component purl, the image digest or a digest-independent scope, a reason, an approver, and an
  expiry date; an expired or malformed waiver is ignored. A waived KEV finding does not block, is listed in the evidence, and is never hidden. Who may approve and whether a waiver may outlive one image are
  questions for George and are not answered here.
* **Evidence.** The gate leaves a JSON report as a workflow artifact, a job-summary table, and an attestation of the verdict bound to the digest: catalog version, release time, fetch time and SHA-256 of the
  catalog bytes, scanner versions and database build time, the findings considered, each blocked or waived item, and the decision. The report is what a later auditor reads to learn why an image was or was not promoted.

Measured today (ran): the tap-web arm64 digest `d86ebb77...` has no KEV-listed vulnerability (catalog 2026.10.15, 1746 entries), so the gate would pass it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-21-1 | KEV blocks promotion | Proposed | An image with a finding whose any alias is in the freshly fetched KEV catalog is not promoted. | |
| req-cicd-sbom-21-2 | Fresh, not attested | Proposed | The decision uses a catalog fetched at promotion and a rescan with the current database; the attested stamp alone never clears an image. | |
| req-cicd-sbom-21-3 | Unobservable blocks | Proposed | A catalog fetch, parse or scan failure blocks promotion. | |
| req-cicd-sbom-21-4 | Evidence is kept | Proposed | Every gate run, pass or block, emits the report described above, with the catalog stamp. | |
| req-cicd-sbom-21-5 | Waivers are visible and expire | Proposed | Pending ruling: a waived item is listed in the report and its waiver expires. | UNRULED. |

### Signer Trust
----
RID: `req-cicd-sbom-22`

Status: `Proposed`

**Decided (SV-8, George 2026-10-15).** TAP keeps a **default-deny trust list of signer identities**, declared as data (a committed JSON file with a JSON Schema and descriptions, per the repository rule for
new structured formats). On ingest TAP verifies the attestation, then checks: the **signer identity** against the list; the **subject digest** against the image digest being ingested; and the **predicate
type** against the expected type. The list starts with **exactly one** signer: the reusable workflow of `req-cicd-sbom-17` at a pinned ref, which teams call from their own repositories, so one identity scales to every team.

**What was verified about identities.** The Sigstore certificate GitHub records carries these fields (read: the Fulcio OID table, `sigstore/fulcio` `docs/oid-info.md`; ran: the real tap-web
bundle for digest `d86ebb77...`, which parsed with `openssl x509`):

| Certificate field | Meaning (OID table, read) | Real value (ran) |
| --- | --- | --- |
| Subject Alternative Name (URI) | the signing workflow reference | `https://github.com/unified-systems-com/tap/.github/workflows/publish-images.yml@refs/heads/main` |
| 1.3.6.1.4.1.57264.1.9 Build Signer URI | `job_workflow_ref` | same value |
| 1.3.6.1.4.1.57264.1.10 Build Signer Digest | `job_workflow_sha` | `cbe3e70045100dd335a82904e6ad2a8fccdd0ebb` |
| 1.3.6.1.4.1.57264.1.12 Source Repository URI | `repository` | `https://github.com/unified-systems-com/tap` |
| 1.3.6.1.4.1.57264.1.14 Source Repository Ref | `ref` | `refs/heads/main` |
| 1.3.6.1.4.1.57264.1.18 Build Config URI | `workflow_ref` | same as the signer (workflow not reusable) |
| 1.3.6.1.4.1.57264.1.11 Runner Environment | `runner_environment` | `github-hosted` |
| 1.3.6.1.4.1.57264.1.21 Run Invocation URI | the run and attempt | `.../actions/runs/36062106865/attempts/1` |

**What was NOT verified, stated plainly.** The real bundles inspected are from a workflow that is NOT reusable, so signer, repository and config all name the same repository. For a reusable workflow, GitHub's
page on reusable workflows and attestations says the signing workflow "will always be the workflow that uses the" attest action, "which may be a reusable workflow", and that the attestation is fetched from the
caller (read, via a page fetch that returned summaries, not the full page). Combined with the OID table's mapping, the inference is: Build Signer URI and the SAN name the REUSABLE workflow, while Source
Repository URI and Build Config URI name the CALLING repository and workflow, which gives per-team attribution. **This is inferred; no reusable-workflow bundle was inspected** (the plugin release lane
`plugin-release-sbom.yml` is reusable, but its header comment says its attestations are "signed by the CALLING plugin repo's workflow identity", which disagrees with the inference; no plugin
attestation was available to settle it, NOT OBSERVED). An implementation MUST test one real bundle from a called reusable workflow before the list is relied on.

**Pinning.** The ref in the SAN is a tag or branch name and can move. The trust entry therefore pins the repository, workflow path and ref AND the **Build Signer Digest** (`job_workflow_sha`, an immutable
commit), so a moved tag does not inherit trust. Tool pins (Syft, Grype, Trivy) are by immutable release and commit digest for the same reason (`req-cicd-sbom-29`).

**Time.** The time TAP records for a document is the signature's own time: the transparency-log `integratedTime` in the bundle, never the document's self-reported `metadata.timestamp`. On the real bundle
the tlog integrated time was 2026-09-24T21:39:05Z (`1790285945`, ran) against a document timestamp of 21:37:49Z, and the signing certificate was valid for ten minutes (21:39:05 to 21:49:05). Verification
that the signing time falls within the certificate validity is performed by the verifier, not reimplemented by TAP.

**What a verified attestation proves.** It says WHO produced a document (a trusted workflow identity, at a commit, in a repository) and WHEN it was signed, and, by George's ruling that CI is trusted, that
the named CI job ran the named tools at the named versions and recorded their output. It does NOT say the contents are true: a scanner can be wrong or itself compromised (Trivy was, in March, as relayed), and a
compromised or mistaken generation step can sign a false document bound to the right digest (the Residual named in `req-cicd-sbom-4`); a false-clean scan is signed just as validly as a true one.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-22-1 | Default deny | Proposed | An attestation whose signer is not in the trust list is refused; an absent or unreadable list refuses everything. | |
| req-cicd-sbom-22-2 | Three checks on ingest | Proposed | Signer identity, subject digest and predicate type are each checked; failure of any one parses nothing: no package, library, finding or other graph content is created from the document. The only record a failed document may leave is the metadata-only audit record of `-22-9`. | Clarified by the CI-side spec after the Codex review of PR# 1045 - tap found `-22-2` and `-22-9` read as contradictory. |
| req-cicd-sbom-22-3 | One signer, plus one transitional | Proposed | The list ships with the reusable workflow at its pinned commit (observed on the first real signed run, run 38955198175 - tap: signer identity `...sbom-vulnerability-evidence.yml@5736329d...`, Build Signer Digest the same commit, Build Config the dispatch caller on `refs/heads/main`) and one transitional entry for `publish-images.yml@refs/heads/main`, which signs revision 1 and has no fixed digest. | Decided with George 2026-10-16 (Q7a). The transitional entry is removed when `publish-images.yml` calls the reusable workflow. Read: the real tap-web attestation verified with signer digest `7cc8f759...`, a commit that moves with every build. |
| req-cicd-sbom-22-4 | Signature time | Proposed | The recorded signing time is the transparency-log integrated time. | |
| req-cicd-sbom-22-5 | Reusable-workflow identity is proven | Proposed | Before the list is relied on, a bundle from a real called reusable workflow is inspected and the signer and calling-repository fields recorded. | OBSERVED for a same-repository caller (2026-10-15, throwaway run 38818229225 - tap, branch since deleted): Subject Alternative Name and Build Signer URI (1.3.6.1.4.1.57264.1.9) named the REUSABLE workflow `.../.github/workflows/r2-reusable.yml@refs/heads/tmp/r2-ci-tests`; Build Config URI (`.18`) named the CALLER `.../r2-caller.yml@...`; Build Signer Digest (`.10`) was a commit sha; Source Repository (`.12`) was the repository. This supports the inference above and contradicts the plugin lane comment. A caller in a DIFFERENT repository was not tested, so what Source Repository says there is NOT OBSERVED. |
| req-cicd-sbom-22-6 | Per-team attribution | Proposed | The calling repository is recorded on the SBOM node alongside the signer. | Depends on 22-5. |
| req-cicd-sbom-22-7 | Trust list is data with a schema | Proposed | The list is one committed JSON file (`scripts/sbom/trusted-signers.json`) with a JSON Schema. An entry names `id`, `repository`, `workflow_path`, `ref` (a branch or tag ref, or a 40-hex commit when the workflow is called by commit), `signer_digest`, `reason` and `added_by`; `signer_digest` is 40 hex characters, or null only when the entry says `transitional: true`. An unknown field, a null digest without the marker, or an empty list is a load failure. | Repository rule for new structured formats. Implemented in `scripts/sbom/select_input.py`. |
| req-cicd-sbom-22-8 | Verification is delegated, with the entry's values | Proposed | The consumer verifies each trusted signer with `gh attestation verify oci://<image>@<digest> --owner <owner> --predicate-type https://cyclonedx.org/bom --cert-identity <https://github.com/repository/workflow_path@ref>` and, when the entry pins a digest, `--signer-digest <signer_digest>`; TAP does not reimplement certificate checks. | The flags exist in gh 2.100.0 (read, `gh attestation verify --help`). Ran: the real tap-web attestation verified (exit 0, one attestation, signer `publish-images.yml@refs/heads/main`). `--cert-identity` matches the exact signer workflow and ref. |
| req-cicd-sbom-22-9 | Outcome is tri-state | Proposed | Verification yields `verified`, `refused` (with the failing check named) or `not-observable`; only `verified` is parsed, and the other two are recorded on the SBOM node, never dropped. The node of a `refused` or `not-observable` document holds metadata only (digests, signer if readable, the failing check). The exclusion of such nodes from consumer queries is `req-cicd-sbom-24-6`. | Feeds `sbom_document.verified`; the mapping onto the node is `-24-6`. |
| req-cicd-sbom-22-10 | Growing the list is reviewed | Proposed | The trust list has a CODEOWNERS rule, and a pull request that adds or loosens an entry (a broader `workflow_path`, a dropped `signer_digest`, a removed pin) is reported in its body. | An allowlist that grows is a weakened control (AGENTS.md review contract). |
| req-cicd-sbom-22-11 | Attribution stays per entry | Proposed | Trusting the signer does not remove per-entry `tools` attribution (`-18-2`): the page and traceability still show which scanner reported what. | George: signer is the trust anchor; `tools` is for traceability. |

### Dependabot Intake
----
RID: `req-cicd-sbom-23`

Status: `Proposed`

**Decided (SV-7, George 2026-10-15): Dependabot alerts are fetched in CI.** The lane lists the calling repository's Dependabot alerts through the REST API and carries them as findings of a scanner
named Dependabot. GitHub's documentation, as the task brief cites it, says `security-events: read` lets a workflow list the repository's Dependabot alerts. **That permission claim is FALSE as stated (ran, `-23-4`): `security-events: read` returned 403; the workflow permission that works is `vulnerability-alerts: read`.** The earlier note, written before the test: the REST
page I fetched states that classic tokens need the `security_events` scope (`public_repo` for public repositories only) and does not mention `GITHUB_TOKEN` or a workflow `security-events` permission; it was not tested
(no token was used). It also does not say what the alert contains about the installed version: an alert records a vulnerable version range, not the installed version (inferred from the API shape; NOT OBSERVED
in a live response), so matching to the SBOM requires evaluating the lockfile version against the range.

**Cases where the token cannot read alerts.** Workflows triggered by Dependabot, and runs from forks, receive a read-only token without the repository's secrets and may not be granted the permission
(GitHub's general rule for fork and Dependabot runs; NOT re-read in full here). In those cases, and on any 403, 404 or timeout, the lane MUST record `tap:dependabot:status = not-observed` with the reason in the
document and in the job summary. It MUST NOT write an empty alert list: an empty list means "looked and found none".

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-23-1 | Alerts fetched in CI | Proposed | When permitted, the lane fetches the repository's Dependabot alerts and records each with its alert number and state. | |
| req-cicd-sbom-23-2 | Not-observed marker | Proposed | In a fork run, a Dependabot-triggered run, or on an API failure, the document records `not-observed` with a reason, never an empty list. | |
| req-cicd-sbom-23-3 | Matched by installed version | Proposed | An alert is attached to a component only when the component's exact version lies in the alert's vulnerable range; otherwise it is reported as unmatched. | |
| req-cicd-sbom-23-4 | Permission claim tested | Proposed | The job that lists alerts declares `permissions: vulnerability-alerts: read`; `security-events: read` alone is not enough. | OBSERVED (2026-10-15, throwaway run 38818229225 - tap, ran): with `security-events: read` and `vulnerability-alerts: read` the call `GET /repos/{repo}/dependabot/alerts` returned HTTP 200 and 48 alerts (header `X-Accepted-Github-Permissions: vulnerability_alerts=read`); the earlier run 38818096043 with `security-events: read` alone, and a control with neither, returned HTTP 403 "Resource not accessible by integration". Same-repository, push-triggered run only; a fork run and a Dependabot-triggered run were not tested. |

### Ingestion - SBOM Node, Parser and Ownership
----
RID: `req-cicd-sbom-24`

Status: `Proposed`

**Decided (SV-3, George 2026-10-15): `computing_core` owns the SBOM node and the parser.** This overrides the lean toward a new `*_core` plugin in `req-cicd-sbom-16` (reconciled below). The vocabulary
change itself (a new node type and edges) is made in the computing_core plugin repository by its own reviewed change; this spec fixes the contract that change must satisfy and does not edit that repository.

**Ingestion order (verify first).** (1) Obtain the attestation bundle for the digest. (2) Verify it with `gh attestation verify` (or the equivalent library call) for the digest and predicate type. (3) Check
the signer against the trust list (`req-cicd-sbom-22`). (4) Parse ONLY the `statement.predicate` that verification returned, never a separately fetched file. Ran (by another session, recorded in
`req-cicd-sbom-16`): exit 0, one verified attestation, the returned predicate byte-identical to the downloaded document. A failed or unobservable verification ingests nothing.

**The SBOM node keeps metadata, not the document.** (George's ruling: the full document is not stored in the database.) It records: subject digest; format and spec version; `serialNumber`; generator
and version; the document's self-reported timestamp; the signature's integrated time (`req-cicd-sbom-22`); the signer identity and calling repository; the attestation reference (transparency-log index and
attestation locator); the verification outcome; the document's **content digest**; the CycloneDX `version` (revision number, `req-cicd-sbom-20`); and a **reference to the stored file**. The file store is tap#1035 (open); until it exists the reference field is `null`
(unobserved), not a path to a non-existent file. The parsed content is reproducible from the stored file, so the file must be the verified predicate bytes.

**The parser maps the document onto grid types that are merged and released**, per the computing_core and compliance_core plugin specs (read, clones at the v0.7.0 and v0.5.0 releases):

| CycloneDX element | Grid result | Method |
| --- | --- | --- |
| component, purl type `apk`, `pypi`, `npm` | `package` keyed `(ecosystem, name, version)`; `purl`, `cpe`, `license`, `architecture` copied; `source_document: sbom` | read (spec) |
| component built or vendored outside a package manager (`tap:supplemental`, `pkg:generic`) | `library`; `SHIPS_LIBRARY` where a package ships it | read |
| `syft:metadata:originPackage` (complete) with the purl `upstream=` qualifier (a subset) | `source_package`, `DERIVES_FROM_SOURCE_PACKAGE` from every package | read; `req-cicd-sbom-16` records the 101/101 and 54/101 counts |
| `metadata.component` operating-system component | `operating_system`, `RUNS_OPERATING_SYSTEM` from the image host | read; the host for an image digest is `req-cicd-sbom-16` decision D, still open |
| vulnerability entry | `compliance_vulnerability` keyed `vuln_id` (CVE, else GHSA; others in `aliases`); CVSS, CWE, SSVC and KEV fields with their sources | read |
| (component x vulnerability x scanner) | `compliance_finding` keyed `(source, source_key)`; `CARRIES_COMPLIANCE_FINDING` from the package or library; `CONCERNS_COMPLIANCE_VULNERABILITY` with `fixed_versions` | read |
| scanner and execution | `compliance_scanner` keyed `(source, scanner_key)`; `compliance_scan_run` keyed `(source, run_key)`; `PERFORMS_COMPLIANCE_SCAN_RUN`, `REPORTS_COMPLIANCE_FINDING`; `RUNS_AT_LOCATION` to the workflow location when it is on the grid | read |
| `tap:crypto:*` properties | `crypto_provider` keyed `(scope, artifact, provider)`; `CARRIES_CRYPTO_PROVIDER` | read; `req-cicd-sbom-16` |
| dependency links | `req-cicd-sbom-28` | |

Findings have no `first_seen`/`last_seen` columns: the finding model carries `name`, `summary`, `description`, `status` (`open` or `resolved`), `source`, `source_key` (read). "Last seen" is therefore the
scan run that reports the finding (`REPORTS_COMPLIANCE_FINDING` points from the latest run that saw it, earlier runs being history, read), and resolution is `status: resolved`.

The `source` written on every node and edge of this parser is `computing_core` (the owning plugin's slug, as the assigned-identity section of the compliance_core spec defines `source`). The compliance_core and
computing_core vocabularies are used unchanged; the one gap found is stated in `req-cicd-sbom-26` (triage coverage).

**Reconciliation with `req-cicd-sbom-16`.** That requirement's Decision 5 table row for "the whole document" says the SBOM node holds the full JSON, and its Open decision B recommends a new `*_core` plugin. Both are superseded by
the ruling here (metadata and a file reference; `computing_core` owns), and the text in `req-cicd-sbom-16` is edited accordingly in this same change.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-24-1 | Verify before parse | Proposed | Only the predicate returned by a successful verification, for the expected digest, predicate type and trusted signer, is parsed. | Extends `req-cicd-sbom-16-9`. |
| req-cicd-sbom-24-2 | Metadata, not the document | Proposed | The SBOM node stores no copy of the document; it stores metadata and a file reference that is `null` until the file store exists. | |
| req-cicd-sbom-24-3 | Released types only | Proposed | The parser writes only node and edge types present in the released compliance_core and computing_core; a type that is not released is not invented in a project. | No bespoke code in a project. |
| req-cicd-sbom-24-4 | One generic parser | Proposed | The parser is the same parser `req-cicd-sbom-16-10` names; the vulnerability mapping is a step of it. | |
| req-cicd-sbom-24-5 | Owner is computing_core | Proposed | The SBOM node, its edges and the parser are specified and released in the computing_core plugin. | Cross-repository change. |
| req-cicd-sbom-24-6 | Only verified documents are read | Proposed | Every consumer-facing selection of component, finding or vulnerability data reads only documents whose `verified` is true. On the SBOM node `verified` is true for a `verified` outcome, false for `refused` and null for `not-observable` (`req-cicd-sbom-22-9`). A `refused` or `not-observable` document leaves a metadata-only record: its digests, the signer if readable, and the failing check, and nothing from its contents is parsed. | Wording agreed with the grid session (rampart-pg, 2026-10-15), which owns the node and its queries. The column that holds the failing check is named in the computing_core spec, not here. |

### Idempotency and Duplicates
----
RID: `req-cicd-sbom-25`

Status: `Proposed`

These are the rules that decide what a second ingest does. They follow from the identities above; the method for each is stated.

1. **Document identity is the content digest, never the `serialNumber` or `version`.** Revisions of one document share a serial and differ in `version` (`req-cicd-sbom-20`). The SBOM node is keyed by the SHA-256 of the exact verified predicate bytes. Evidence (read, the two arm64 and amd64 documents): `serialNumber`
   and `metadata.timestamp` are different on every Syft run even for the same image; so identity by `serialNumber` would make every run a new document and identity by digest makes identical bytes one document.
   Re-ingesting identical bytes is a no-op: no node, edge or field changes.
2. **A new revision, or a regenerated document, for the same digest is a new SBOM node and creates no new component nodes.** `package`, `library`, `source_package`, `operating_system` and `compliance_vulnerability` are
   keyed by natural keys (`(ecosystem, name, version)`, `vuln_id`), so a second document for the same digest resolves to the existing nodes (inferred from the keys; the released plugin tests for
   re-observation are read in the plugin specs, not run).
3. **No duplicate findings.** A finding's `source_key` is derived from stable facts only: `sbom:<subject digest>:<component purl>:<canonical vulnerability id>:<scanner_key>`. A re-observation resolves to the
   same finding; its reporting edge is moved to the latest run, and a previously `resolved` finding that is reported again returns to `open` (the history records both changes).
4. **A finding not reported by the newest run for that digest and scanner becomes `resolved`, never deleted.** This is how a retracted vulnerability (database correction, rejected CVE) leaves the open set
   while the history keeps the earlier observation.
5. **Run identity.** `run_key` is `<document content digest>:<scanner_key>`, so the same vulnerability document re-ingested is the same run.
6. **Counts are over distinct (vulnerability, component version), not over findings.** Two per-platform digests of one image have identical component identities (ran: each document's 191 components reduce to 182 distinct
   `(ecosystem, name, version)` keys and the two sets are identical, 182 in common; the 9 in-document repeats were not investigated), so counting findings would double count; every count shown to a human groups by `(vulnerability, package or library version)` over the set of images in scope. Optionally a second grouping by `source_package` (the 14 package names of the Trivy alerts reduce to 6 sources, read in the computing_core spec).
7. **Identical triage across architectures.** Rules 3 and 6 mean amd64 and arm64 each have their own findings (their `source_key` differs by digest) and one human-facing count.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-25-1 | Identical bytes are a no-op | Proposed | Ingesting the same verified predicate bytes twice changes nothing. | |
| req-cicd-sbom-25-2 | New document, no new components | Proposed | A new revision for one digest adds one SBOM node and no package, library, source_package or vulnerability node. | |
| req-cicd-sbom-25-3 | Stable finding key | Proposed | A finding's `source_key` is the digest, purl, canonical vulnerability id and scanner; a re-observation never mints a second finding. | |
| req-cicd-sbom-25-4 | Unreported means resolved | Proposed | A finding absent from the newest result for its digest and scanner is `resolved`, not deleted; a reappearance reopens it. | |
| req-cicd-sbom-25-5 | Human counts group by vulnerability and version | Proposed | A displayed count groups by (vulnerability, component version), so two architectures of one release count once. | |

### Current Semantics, Counting and Triage
----
RID: `req-cicd-sbom-26`

Status: `Proposed`

**"Current" is defined, not assumed.** An image digest is immutable; its component list is fixed. Its vulnerabilities change daily. There are therefore many vulnerability results per digest over time, each
true as of its timestamp. **Current = the highest `version` of the document per digest (`req-cicd-sbom-20`), which carries the latest run of each scanner that ran in it; a scanner absent from that revision is recorded as not run, and its previous results stay as history. Older revisions, runs and resolved findings are never deleted.**

**Fleet counts are over deployed images.** A count joins from the SBOM's subject digest to what is deployed on the grid (the host, task or image record that runs that digest). A count that cannot make
that join states "deployment not observed" and does not fall back to every image ever imported. Whether the grid has a deployed-digest record today is NOT OBSERVED; the join is a requirement on whichever
collector supplies it.

**Triage is an authored judgement on top and survives new images.** `false_positive`, `not_affected` (with a CycloneDX VEX justification) and other `analysis` states are decisions about a vulnerability
in a component version, not about one image: when the same (vulnerability, component version) recurs in a new image, the earlier judgement still applies, subject to its own expiry. Because findings are per
digest (`req-cicd-sbom-25`), the judgement cannot hang on a finding alone. Proposed rule: a judgement is recorded as a compliance exception covering one anchor finding, and ingestion draws the same
`COVERS_COMPLIANCE_FINDING` edge to every new finding with the same vulnerability and the same package or library node while the exception is in force. **Gap:** the released `compliance_exception` model
has `name`, `description` and `status` only (read, spec); the scope (which vulnerability, which component) would be derived from the anchor finding's edges rather than stored. Whether that is enough, or a
compliance_core change is needed, is NOT OBSERVED and is left to that plugin's review.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-26-1 | Current is the latest revision | Proposed | A "current" view per digest uses the highest document `version` and the latest run of each scanner; no older revision, run or finding is deleted. | |
| req-cicd-sbom-26-2 | Counts join to deployment | Proposed | A fleet count includes only digests that are currently deployed on the grid; absent deployment data it reports "not observed". | |
| req-cicd-sbom-26-3 | Triage survives a new image | Proposed | An in-force judgement for (vulnerability, component version) covers the matching finding of a later image without re-authoring. | |

### Alert-Derived and SBOM-Derived Duplicates
----
RID: `req-cicd-sbom-27`

Status: `Proposed`

**Decided (SV-6, George 2026-10-15): keep both and correlate.** An alert-derived finding and an SBOM-derived finding for the same CVE, component version and image are the same vulnerability. Alerts keep the
first-seen date and the dismissal reason; the SBOM supplies what is present now. Alert-derived component findings are retired LATER, once triage and first-seen dates live in the new flow. Counts shown to humans group
by (vulnerability, component version), so they do not double.

**The problem, from the data.** GitHub code-scanning alerts enter the grid as `compliance_finding` nodes keyed `("github_core", "<repo>#code_scanning#<number>")` (read, compliance_core spec); SBOM findings are
keyed by `req-cicd-sbom-25`. The key spaces never collide, so without a rule one vulnerability on one component in one image is two findings. Real example (read: the grid export of 2026-10-14; ran: matched against
Grype on the Sep-24 arm64 SBOM; the two dates differ, so this is a sample, not a reconciliation): alert 454 - tap, Trivy, `CVE-2026-49265`, message "Package: oauthlib Installed Version: 3.3.1 ... Fixed Version: 4.0.0",
category `trivy-tap-web`, located at `opt/uv-cache-seed/.../oauthlib-3.3.1.dist-info/METADATA` (the wheel cache, which `req-cicd-sbom-2` excludes). The SBOM lists `oauthlib 3.3.1` in the locked closure and Grype on
it reports that CVE on it. Same vulnerability, same package version, different location: a location match would call them different, the pair below calls them the same. Of the 143 alerts in the `trivy-tap-web`
category, 79 (57 fixed, 22 open) have an exact (CVE, package, version) match among Grype's findings on the SBOM; 64 do not (the alert side is older or newer than the SBOM, or the alert is on a path the SBOM
excludes; the split was not investigated). Of all 400 alerts, 108 are located in the wheel-cache seed (106 fixed, 2 open).

**What makes two findings "the same" (the correlation key).** Two findings are the same item when ALL of:

1. **Same canonical vulnerability id.** CVE if either side knows a CVE alias, otherwise GHSA; the alert's `rule_id` is checked against the alias set of the SBOM-side vulnerability.
2. **Same component identity.** Package or library name normalised as the ecosystem does (lowercase; for pypi, PEP 503 normalisation, `_` equals `-`) AND the exact installed version. The alert carries name and
   version only inside its `message` text ("Package: ... Installed Version: ..."), so the correlator parses that text and, if it cannot parse it, does NOT correlate (a false merge is silent and
   unrecoverable, a false split is visible: the compliance_core scanner rule of thumb, read). If one name and version exists in two ecosystems the pair is ambiguous and is not correlated.
3. **Same image scope.** The alert's `category` names the image (`trivy-tap-web`, `grype-declared-tap-db`) and its `commit_sha` and `ref` name the build; the SBOM finding names the digest. Correlate when the digest is
   one the grid records as built from that commit, or, for the nightly sweeps of `:latest`, one of the image's currently deployed digests. Which digest an alert's analysis actually scanned is NOT OBSERVED
   (the alert carries a commit, not a digest); until the grid records it, scope is the image name plus the deployed-digest rule, and the correlator says so on the item.

Correlation is computed from shared graph facts, not stored as a new edge: both findings must reach the same `compliance_vulnerability` node and the same `package` or `library` node. The SBOM parser draws
`CARRIES_COMPLIANCE_FINDING` from the package to its findings (`req-cicd-sbom-24`). Whether the alert collector draws that edge from the package to its alert findings is NOT OBSERVED (the alert finding is
attached to the repository in the export, and a package node is not among its nodes); if it does not, the alert side needs it (a github_core change) before the key is mechanical, or the correlator derives the
package from the alert text at read time.

**What each side contributes.**

| Fact | Comes from | Why |
| --- | --- | --- |
| First seen | the alert's `created_at` (the earlier of it and the SBOM side's earliest observation) | alerts hold the history; a finding has no first-seen column (read) |
| Dismissal (state, reason, comment, who, when) | the alert (`dismissed_at`, `dismissed_reason`, `dismissed_comment`, `dismissed_by_login`) | an authored judgement |
| Present now, and in which digest | the SBOM finding (the newest revision, `req-cicd-sbom-20`) | the SBOM is the component record and is rescanned |
| Fix versions, KEV, SSVC, EPSS, CVSS | the SBOM-side vulnerability facts with provenance (`req-cicd-sbom-18`) | enriched with sources |
| Location | the alert (a file path); the SBOM side has the component, not a path | different questions |

**When they disagree.**

| Alert says | SBOM says | Result |
| --- | --- | --- |
| open | lists the pair | one open item |
| dismissed (any reason) | lists the pair | one item shown as dismissed-with-reason, not counted open; the dismissal applies to that exact (vulnerability, component version) only (`req-cicd-sbom-26`) and lapses if the component version changes; the SBOM finding stays `open` in the graph and the item displays the alert's dismissal |
| fixed or closed | lists the pair | present now wins: one OPEN item flagged `alert-closed-sbom-present`, because the SBOM says the component is there; the flag is a difference to explain, not a silent override |
| open | does not list the pair | one item, flagged `alert-only` (the 64 above): counted, because the alert may see something the SBOM excludes by design (`req-cicd-sbom-2`), and flagged so a human knows the SBOM record disagrees |
| no alert | lists the pair | one item, `sbom-only` |

**Counting.** The number shown to a human is the number of distinct items, grouped by (vulnerability, component version) over the images in scope (`req-cicd-sbom-25-5`); an item's status follows the table.

**Later retirement of alert-derived component findings (not now).** Retirement is triggered, and only then proposed to George, when all three hold: (a) triage lives in the new flow (the
`req-cicd-sbom-26` judgement path is built and has absorbed the alerts' dismissals); (b) first-seen dates are held on the SBOM side (a field or history the finding model does not have today, read); (c) a parity
measurement over a stated window shows every open alert-derived component finding is either correlated with an SBOM finding or explained as `alert-only` for a stated reason. Retirement itself marks the
alert-derived finding `resolved` with the reason `superseded`, and stops collecting component alerts; it is not a deletion. Code-scanning alerts that are not component vulnerabilities (CodeQL, SonarCloud)
are out of this requirement.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-27-1 | Correlation key | Proposed | Two findings correlate only on equal canonical vulnerability id, normalised component name plus exact version, and image scope; an unparseable or ambiguous alert is not correlated. | |
| req-cicd-sbom-27-2 | Contributions are fixed | Proposed | First seen and dismissal come from the alert; presence now and enrichment come from the SBOM side. | |
| req-cicd-sbom-27-3 | Disagreements are shown | Proposed | `alert-closed-sbom-present`, `alert-only` and `sbom-only` are surfaced on the item; none is silently resolved. | |
| req-cicd-sbom-27-4 | No double count | Proposed | A correlated pair is one item in every count. | |
| req-cicd-sbom-27-5 | Retirement waits for parity | Proposed | Alert-derived component findings are retired only after triage, first-seen and a measured parity exist in the new flow. | |

### Dependency Links as Edges (Provisional)
----
RID: `req-cicd-sbom-28`

Status: `Proposed`

**Decided (SV-4, George 2026-10-15): the `dependsOn` links BECOME EDGES, "yes for now".** This is **provisional** (below).

**Edge.** `REQUIRES_PACKAGE`, sentence `<package> REQUIRES_PACKAGE <package>`, owned by computing_core (`req-cicd-sbom-24`). Name check against the repository's edge-naming rule (`req-tap-plugin-edge-naming`,
read: `bare-verb`, `modal-prefix`, `trailing-preposition`): two tokens, no modal prefix, ends in a noun. `DEPENDS_ON` alone is a bare verb plus a trailing preposition and `DEPENDS_ON_PACKAGE` would pass but repeats the
modal feel; `REQUIRES_PACKAGE` was chosen for the plain verb. The name was reasoned against the rules read in `tap_plugins/validate/service.py` (`_EDGE_MODAL_PREFIXES`, `_EDGE_PREPOSITIONS`); the validator was not run on it
(NOT OBSERVED).

**Facts about the links (ran, `dependencies[].dependsOn` of the two real documents).** arm64: 458 links (356 apk, 88 pypi, 14 npm), amd64: 420 (318 apk, 88 pypi, 14 npm); all resolve; every link joins two
`package`-type components (no link touches a library or the operating-system component). After reducing components to `(ecosystem, name, version)` the distinct pairs are 451 (arm64) and 413 (amd64); 411
pairs are common to both, 40 are arm64-only, 2 amd64-only, so 453 distinct edges for the two documents together.

**Identity.** The edge declares the plain identity (type, source, target) with **no architecture or digest discriminator.** Justification: the link is a fact about two package releases ("this
apk release requires that one"), which holds wherever those releases are installed; and a discriminator by subject digest would write about 878 edges for this one release pair (458 + 420), nearly all duplicates of each
other, and repeat that for every release and every image, while the undiscriminated edge adds only the pairs not already present (453 here). Cost accepted: the edge cannot say which architecture or image had the
link, and a link that disappears from a later document is not retracted by the edge (the document the SBOM node refers to still holds the exact per-digest graph, in the stored file).

**Provisional.** Revisit when any of these holds: the edge count per document or in total makes ingestion slower than the benefit (cost per document); a Gryphon query or panel actually traverses `REQUIRES_PACKAGE`
(if nothing queries it after a quarter of use, drop it: the stored file keeps the graph); a question needs the per-image or per-architecture graph, which would need the discriminator or the file.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-28-1 | Links become edges | Proposed | Every `dependsOn` link between two `package` components becomes a `REQUIRES_PACKAGE` edge; a link touching another component type is reported, not dropped. | |
| req-cicd-sbom-28-2 | Plain identity | Proposed | The edge declares no discriminator, so a re-ingest or a second architecture adds no duplicate edge. | |
| req-cicd-sbom-28-3 | Provisional is recorded | Proposed | The revisit conditions above are recorded with the edge definition. | |
| req-cicd-sbom-28-4 | Name passes the naming check | Proposed | `validate_plugin` accepts the slug. | NOT OBSERVED. |

### Scanner Pin Maintenance
----
RID: `req-cicd-sbom-29`

Status: `Proposed`

**Decided (SV-9, George 2026-10-15): add Renovate managers for the Syft and Grype pins; BUILD LATER, not now.** No Renovate manager watches them today (the task brief; the repository's `renovate.json5` was
read only for its trivy-action rule). The pins are: `grype-version` in `.github/workflows/grype-nightly.yml` (currently `v0.118.0`, read, while v0.120.1 exists and was run) and the `SYFT_IMAGE` tag plus digest in
`scripts/sbom/generate.py` (currently `v1.51.0@sha256:678bfa56...`, read; v1.54.1 exists and was run). Pins are by immutable release and commit digest (the `SYFT_IMAGE` already is; the Grype pin is a tag today). One grouped Renovate PR moves them together because the tests keep copies of the version equal (the tests
were not read), and a minimum release age SHOULD apply so a just-published scanner release is not adopted the same day.

Trivy is NOT specified here beyond a reference: the Trivy pin gap is tap#1038 (Renovate does not watch it, and the `aquasecurity/trivy-action` disable rule may no longer hold); it waits on the test that issue describes.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-29-1 | Pins are watched | Proposed | A Renovate manager proposes updates for the Syft and Grype pins, grouped into one PR. | Built later. |
| req-cicd-sbom-29-2 | Release age | Proposed | The group sets a minimum release age. | |
| req-cicd-sbom-29-3 | Trivy deferred to tap#1038 | Proposed | Trivy is covered by the issue, not by this requirement. | |

### What This Feeds - CBOM and VDR
----
RID: `req-cicd-sbom-30`

Status: `Proposed`

**Feeds `req-cicd-sbom-16` (the CBOM).** The parser that maps packages, libraries and source packages is the parser that maps `tap:crypto:*` properties (`req-cicd-sbom-16-10`); the trust list, verification,
document identity and file reference built here are the same ones the CBOM uses. The CBOM needs no second attestation, no second ingestion path and no second node: it inherits all of `req-cicd-sbom-22` to `-25`.

**Will drive VDR processing (not specified here).** VDR is not specified by this group. What a VDR consumer needs from the grid, and which requirement supplies it:

| Need | Supplied by |
| --- | --- |
| A current open vulnerability set per deployed image | `req-cicd-sbom-25` (stable findings, resolved on absence), `-26` (current, deployed) |
| Fixed versions per vulnerability and component | the `fixed_versions` property of `CONCERNS_COMPLIANCE_VULNERABILITY` |
| KEV, SSVC and EPSS facts with provenance | `req-cicd-sbom-18` (source, retrieval time, catalog version) |
| Triage state | `req-cicd-sbom-26` (judgements that survive) |
| Who produced the evidence and when | `req-cicd-sbom-22` (signer, signature time) |

The existing VDR vocabulary in the FedRAMP plugin is outside this scope and untouched.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-30-1 | CBOM shares the pipeline | Proposed | The CBOM ingestion path is the one defined in `req-cicd-sbom-24`; no CBOM-specific trust, node or parser exists. | |
| req-cicd-sbom-30-2 | VDR needs are queryable | Proposed | The five needs above are each answerable from the grid by Gryphon without reading the stored file. | |

### SBOM Field Completeness Check
----
RID: `req-cicd-sbom-32`

Status: `Proposed`

Why: a scanner matches on what the SBOM carries. An SBOM that lacks the matching fields does not fail; it quietly reports fewer vulnerabilities, and nobody sees the gap. TAP's own generator keeps the fields today, so the
check protects the case George named: other teams producing CycloneDX SBOMs for field software, where a thin document would under-report without a sign. "Complete" here means **field completeness**, that each component
carries the identifiers a matcher uses. It does NOT mean inventory completeness (that every package in the image is listed); that is `req-cicd-sbom-2`, `-7` and `-12`.

**What the real document carries (ran, `jq` over the attested tap-web arm64 CycloneDX 1.7 document, Syft 1.51.0, 192 components):**

| Ecosystem | Components | With purl | With cpe | With `syft:cpe23` candidate properties |
| --- | ---: | ---: | ---: | ---: |
| apk | 102 | 102 | 102 | 71 |
| pypi | 71 | 71 | 71 | 63 |
| npm | 15 | 15 | 15 | 5 |
| generic | 1 | 1 | 1 | 0 |
| github | 2 | 2 | 0 | 0 |
| operating-system (wolfi 20230201) | 1 | 0 | 0 | 0 |

For the 102 apk components: `arch=` and `distro=` qualifiers on 102; `syft:metadata:originPackage` on 102; the `upstream=` qualifier on 54, which is exactly the 54 whose origin package name differs from the component name
(ran, `jq`). So the upstream qualifier is **conditional on the origin differing**, and a rule demanding it on every apk component would refuse a correct document.

**How much each field is worth (relayed from the support session's ablation, and re-counted here from its output files `gridsbom/out/*.json` with `jq`; Grype v0.120.1 on SBOMs rebuilt from selected fields; the counts are
what I re-counted, the runs themselves are NOT re-run here):**

| Fields kept | Grype matches |
| --- | ---: |
| purl + upstream + cpe + candidates (the original) | 91 |
| purl + cpe + OS, no candidates | 89 |
| purl + OS, no cpe | 50 |
| purl only, no OS component | 50 |
| purl + OS, no upstream and no cpe | 12 |

Two things the ablation does not show, stated so nobody over-reads it: (1) the OS component did not change the result (50 with it and without it), so its value to Grype is NOT demonstrated; it stays required because the grid
side consumes it (`req-cicd-sbom-24`), not because Grype needs it; (2) no run removed the upstream qualifier while keeping cpe, so the separate worth of `upstream=` is NOT OBSERVED.

**The rules are data.** The per-ecosystem requirements live in one committed JSON file with a JSON Schema, not in the check's code (repository rule for new structured formats; "what is required" is declarative, "how it is
checked" is code). The starting rows come from the table above: apk, pypi, npm and generic components require purl and cpe; github components require purl only; every apk component requires `arch`, `distro` and
`syft:metadata:originPackage`, and the `upstream` qualifier when the origin differs; exactly one operating-system component with a name and a version is required.

**Verdict.** The check writes `tap:completeness` into the document: `complete`, `thin` (with a count per named gap class and up to a handful of example components each), or `not-observable` (the check could not run). It is
never absent and never an empty list standing for "complete".

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-sbom-32-1 | Runs on every document | Proposed | The check runs at stage 1b (`req-cicd-sbom-17-6`) over TAP-generated and caller-supplied CycloneDX documents alike, before any scanner reads them. | |
| req-cicd-sbom-32-2 | Rules are a schema-validated data file | Proposed | The per-ecosystem rules are one committed JSON file validated against a committed JSON Schema at load; an unknown ecosystem key, a missing description or an invalid file fails the load. | |
| req-cicd-sbom-32-3 | Required fields per ecosystem | Proposed | A component of a ruled ecosystem lacking a required field is a gap of a named class (`purl`, `purl-qualifier:arch`, `purl-qualifier:distro`, `purl-qualifier:upstream`, `cpe`, `origin-package`). | Starting rows from the table above. |
| req-cicd-sbom-32-4 | Upstream is conditional | Proposed | An apk component whose `syft:metadata:originPackage` differs from its name requires the `upstream=` qualifier; one whose origin equals its name does not. | 54 of 54 on the real document; a blanket rule refuses a correct SBOM. |
| req-cicd-sbom-32-5 | Distro component | Proposed | Exactly one operating-system component with a name and a version must exist for an image SBOM. | Needed by the grid; its worth to Grype is NOT demonstrated. |
| req-cicd-sbom-32-6 | Thin is refused | Proposed | A `thin` verdict fails the run, and the gaps are listed in the job summary. | Decided (SV-10, George: fail first). An opt-in to record `thin` instead is deliberately not specified. |
| req-cicd-sbom-32-7 | Candidates are reported, not required | Proposed | The count of components carrying `syft:cpe23` candidates is recorded in `tap:completeness`; its absence does not make a document `thin`. | Worth 2 of 91 matches in the ablation, and Syft emits candidates only where it has them. |
| req-cicd-sbom-32-8 | Verdict is never silent | Proposed | `tap:completeness` is present in every sealed document; a check that errored records `not-observable` and fails the run. | Three states, never two. |
| req-cicd-sbom-32-9 | Seeded-defect fixtures | Proposed | The check's tests include the real tap-web document (must be `complete`) and one document per defect class built from it by deleting that one field (each must be `thin` naming that class). | Proves the pass is not vacuous. |
| req-cicd-sbom-32-10 | Coverage states its limit | Proposed | `tap:completeness` states that it covers identifier fields and does not cover whether every package in the image is listed. | A `complete` verdict is not an inventory claim. |
| req-cicd-sbom-32-11 | Unruled ecosystem is thin | Proposed | A component whose purl ecosystem has no row in the rules file, or that has no purl and is not the operating-system component, is a gap of class `unruled-ecosystem` and makes the verdict `thin`; the check never passes a component it has no rule for. | Found by the Codex review of PR# 1045 - tap: without this a Maven, Debian, RPM, Cargo or Go SBOM would be called `complete`. Adding an ecosystem is a reviewed change to the rules file. |
| req-cicd-sbom-32-12 | Go modules are ruled | Proposed | The rules file has a `golang` row requiring a purl and a CPE; the tap-db image carries Go modules recorded from the `gosu` binary. | Found by running the check on a real tap-db SBOM (Syft 1.51.0, local image, 2026-10-19): without the row its 4 Go components were `unruled-ecosystem` and the gate would have blocked tap-db publishing. |

### Python Wheel Attributes - License and Architecture
----
RID: `req-cicd-sbom-33`

Status: `Proposed`

Why: the image SBOM lists the locked Python closure from `uv.lock` (`req-cicd-sbom-2`), and a lock entry carries neither a license nor an architecture. The grid reads both: a package's license, and its architecture, which today comes only from a purl `arch=` qualifier and so is empty for every PyPI component.

**What is true of the image (ran, 2026-10-19, against the local `ghcr.io/unified-systems-com/tap-web:latest` image and the attested revision 1 of tap-web `sha256:a9149a88...`; the stack was not booted, only throwaway containers):**

* The image has no installed Python packages: `/app/.venv/lib/python3.14/site-packages` does not exist. The venv is created at container start by `uv sync` from the wheel cache seed at `/opt/uv-cache-seed`. This is why Syft's `python-package-cataloger` reads `uv.lock` (`syft:package:metadataType` is `python-uv-lock-entry` for all 71 pypi components) and why those components have no `licenses`.
* The seed holds 73 unpacked wheels with their `*.dist-info/WHEEL` and `METADATA`. Joined to the 71 locked components by PEP 503 name and version, 68 match. The 3 that do not are `colorama`, `tzdata` and `tap` itself (`req-cicd-sbom-2` already names them as members the cache misses). The seed also holds 5 entries that are not locked (`setuptools` twice, `wheel`, `maturin`, `pycparser`), which the join ignores.
* Of the 68, every one has a license field: `License-Expression` or `License` for 64, a `License ::` classifier only for 4.
* The `WHEEL` files carry the architecture: `pydantic_core-2.46.4` has `cp314-cp314-manylinux_2_17_aarch64`, `cryptography-50.0.0` has `cp314-abi3-linux_aarch64`, `annotated_types-0.8.0` has `py3-none-any`.
* Syft cannot supply the architecture: with `+python-installed-package-cataloger` and no exclusion it found 104 python entries (the 71 lockfile entries and 33 seed extras), and the installed-package entry's `metadata.platform` is the empty string. Its entries do carry licenses (`pydantic_core`: MIT).

**The rule.** The seed is an ATTRIBUTE SOURCE for the components `uv.lock` already lists; it never adds, removes or versions a component (`req-cicd-sbom-2` stands: the seed is available bytes, not running software). Generation reads the `WHEEL` and `METADATA` headers of each seed dist-info, joins by normalized name and version, and writes onto the matching CycloneDX component: `licenses`; a `tap:license:source` property (`expression`, `license` or `classifier`); a `tap:python:wheel-tag` property (the wheel's tags, comma-separated); and a `tap:architecture` property. A pure wheel (platform tag `any`) is `noarch`; a platform wheel is the machine named by its platform tag (`aarch64`, `x86_64`). The purl is NOT changed: it is the identity and the join key for Grype and for the grid, and the pypi purl type has no arch qualifier. The grid parser reads `tap:architecture` for PyPI; that is the grid session's change.

**Unknown is declared.** A component with no matching wheel gets `tap:licenses:status` = `not-observed` with `tap:licenses:reason`, and `tap:architecture:status` = `not-observed` with a reason; never an absent field and never an empty string standing for "none".

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | --- | --- | --- |
| req-cicd-sbom-33-1 | Seed is an attribute source only | Proposed | Attributes come from the dist-info of the cache seed, joined to lockfile components by PEP 503 name and version; the join adds, removes and re-versions no component. | `req-cicd-sbom-2` unchanged. |
| req-cicd-sbom-33-2 | Licenses | Proposed | A matched component's `licenses` is `{expression}` when `License-Expression` is present and a valid SPDX expression, otherwise `{license: {name}}` from the `License` field or a `License ::` classifier; `tap:license:source` names which. | 64 of 68 have an expression or license field, 4 only a classifier (ran). |
| req-cicd-sbom-33-3 | Architecture | Proposed | `tap:architecture` is `noarch` for a wheel whose platform tag is `any`, else the machine of its platform tag; `tap:python:wheel-tag` carries the tags. | Naming of `noarch` is agreed with the grid session. |
| req-cicd-sbom-33-4 | Purl unchanged | Proposed | No purl, `bom-ref` or CPE of a PyPI component is altered by this requirement. | Identity and the Grype join key. |
| req-cicd-sbom-33-5 | Unknown is declared | Proposed | A component with no matching wheel carries `tap:licenses:status` and `tap:architecture:status` = `not-observed`, each with a reason; the fields are never absent, empty or guessed. | Today: colorama, tzdata, tap. |
| req-cicd-sbom-33-6 | SPDX carries the license | Proposed | The SPDX document's package `licenseDeclared` is the matched expression, or `NOASSERTION` when unknown; architecture is carried in the CycloneDX document only. | SPDX 2.3 has no architecture field on a package. |
| req-cicd-sbom-33-7 | Completeness requires them | Proposed | The completeness rules (`req-cicd-sbom-32`) gain a second tier for pypi, `require_attributes`: `licenses` and `tap:architecture`, each present or declared unknown (`-33-5`). Declared unknowns are counted in `tap:completeness:declared-unknown`, and more than the rules file's `declared_unknown_limit` for the ecosystem (5 for pypi) is a gap. A gap in this tier makes the verdict `thin` only when attributes are enforced, as at image generation; a rescan of an older published revision (`-33-9`) reports the gaps in `tap:completeness:attributes` and the job summary and does not fail on them. | Two tiers because license and architecture are inventory attributes for the grid; they do not change what Grype matches, so their absence must not stop a rescan of a revision published before this requirement. Starting limit 5 (observed 3 of 71). |
| req-cicd-sbom-33-8 | A vanished seed is loud | Proposed | If the seed is absent or yields no matching wheel, generation fails through `-33-7` instead of publishing a document whose license and architecture are all unknown. | The seed is an accident of the cache strategy; this is the canary. |
| req-cicd-sbom-33-9 | Existing revisions are unchanged | Proposed | Published revisions are not rewritten (`req-cicd-sbom-20-2`, `-20-3`); the attributes appear in revision 1 of the next image build, a new digest. | A rescan only re-scans a fixed document. |

#### Method summary and NOT OBSERVED

Ran (2026-10-15): grype v0.120.1, trivy 0.75.0 and 0.76.0, syft v1.54.1 in throwaway containers; the CISA KEV catalog and one CVE record fetched; openssl parsing of the two real attestation certificates;
read-only JSON parsing of the real SBOMs and a grid export. Read: the specs, workflows and plugin clones named in the text. CI-side additions (tap#1044, 2026-10-15): `jq` field counts over the attested tap-web arm64 document
and a re-count of the support session's ablation outputs (ran); `gh attestation verify --help` of gh 2.100.0 (read). Not run by this author in that first pass: the ablation itself. Later runs are named where they are used (Grype and Syft in throwaway containers, the workflow in CI). NOT OBSERVED: a reusable-workflow attestation bundle
from a caller in ANOTHER repository (a same-repository one was read, `-22-5`); a fork or Dependabot-triggered run of the alerts call (the push-triggered one was run, `-23-4`); the VEX predicate URI; Grype reading SPDX 3.0.1 (support's claim); Trivy's inability to read SPDX 3; the cause of Trivy's maven non-result; which of Grype's extra apk matches are true
positives; whether `validate_plugin` accepts `REQUIRES_PACKAGE`; whether the grid records which digest is deployed; whether `compliance_exception` can carry an anchor-derived scope.

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
