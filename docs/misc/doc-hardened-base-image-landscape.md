---
spec: ../../specs/spec-cicd-hardening.md
audience: [developer, llm]
covers:
  - ../../specs/spec-cicd-hardening.md
  - req-cicd-base-image-lifecycle
update-triggers:
  - A base-image provider materially changes free-tier / Python-version / extensibility posture
  - TAP adopts the bake-once/distroless runtime variant (re-evaluate DHI / Red Hat Hardened)
  - A customer/engagement introduces a FIPS / FedRAMP / STIG requirement
  - uv ships embedded git (issue #12324) — the git off-ramp opens
assumes:
  - TAP's runtime-install architecture (deps + plugins installed at container start, not baked at build)
provides: |
  The decision record behind req-cicd-base-image-lifecycle: the 2026 hardened-base-image
  landscape, why Wolfi fits TAP's architecture, when to re-evaluate the alternatives, the
  git-binary off-ramps, and the FIPS-crypto analysis (buy vs. DIY OpenSSL-3-FIPS-provider).
---

# Hardened Base Image Landscape + FIPS Analysis

This is the **decision record** for `req-cicd-base-image-lifecycle`. The spec states the
decision (curated-minimal Wolfi base + self-hosted patch loop, demand-gated FIPS); this doc
holds the *why*, the alternatives evaluated, and the triggers for revisiting them — so a future
reader (human or agent) doesn't re-litigate settled ground or miss a re-evaluation moment.

## The decision criterion (read this first)

> **RETRACTED (2026-07-09).** An earlier version of this doc argued: *TAP installs deps + plugins
> at container start, therefore the base must ship a **package manager**, therefore every
> fixed/distroless image is out.* **That is a non-sequitur and it is wrong.**

`uv sync` and `uv pip install git+https://…` are **Python-package** operations, not **OS-package**
operations. They need `python`, `uv`, `git`, `bash` (+ `sed`/`grep`/`coreutils`) — every one of
which can be baked at **build** time by any means. Nothing in TAP's runtime-install architecture
requires `apk`/`apt`/`dnf` to survive into the runtime image. TAP's own `Dockerfile` already proves
the principle: `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/` installs `uv` with no
package manager involved at all.

**Proven by spike** (`spikes/distroless/`, both `BUILD_EXIT=0`) — each using the vendor's *own*
install-into-a-rootfs flow, then copying that rootfs into a package-manager-less runtime:

| Runtime base | Build process | Result |
| --- | --- | --- |
| `cgr.dev/chainguard/python:latest` — no `apk`, no `apt`, **not even `/bin/sh`** | `apk add --root /rootfs --initdb` | Python 3.14.6, git 2.55.0, uv 0.11.28; `uv sync` of TAP's real closure (django 6.0.2 + webauthn); from-git install (click 8.1.7) |
| `registry.access.redhat.com/ubi9/ubi-micro` — no package manager | `dnf -y install --installroot=/rootfs` (Red Hat's documented distroless build) | Python 3.14.5, OpenSSL 3.5.5, `_ssl` → system `libcrypto.so.3`; `uv sync` + from-git install both OK |

So the field is **not** split by package manager. The criteria that actually decide it:

1. **Python-3.14 currency.** `requires-python = ">=3.14"` is the hard filter. Measured: Wolfi
   **3.14.6** · UBI9 `dnf install python3.14` → **3.14.5** · Google Distroless `python3-debian13`
   → **3.13.5** (out; the `debian12` line, showing 3.11.2, is deprecated).
2. **In-image vs host-derived FIPS.** The load-bearing one — see the FIPS section below.
3. **Who patches, how fast**, and whether we can pull without credentials.

**Wolfi is the standard base** (`req-cicd-base-image-lifecycle-3`). Alternatives are **parked, not
eliminated**; the reopen triggers are listed below.

## Provider matrix (2026)

| Provider | Model | libc | Free? | Python 3.14? | Fit now | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| **Chainguard / Wolfi** | pkg-mgr base (`apk`) **and** fixed images | glibc | Yes (`wolfi-base`, apko/melange OSS; catalog free tier is `:latest`-only) | **Yes** (spike: 3.14.6) | **✅ chosen** | Tracks latest; apko/melange = build-your-own for free; commercial catalog adds pinning + SLA + FIPS. |
| **Docker Hardened Images (DHI)** | fixed/distroless | glibc/musl | **Yes** — free + Apache-2.0 since 2025-12-17 | examples show 3.13 | Bake-once only | Docker-native, OSS. **First to benchmark for the bake-once variant.** Enterprise = SLA/FIPS. |
| **Red Hat Hardened Images** | fixed/micro | glibc | **Yes** — GA 2026-05-12, `images.redhat.com` | built-from-upstream (fresher than UBI; 3.14 TBD) | Bake-once only | Distinct from UBI (upstream-built → faster CVE fixes). |
| **Red Hat UBI (micro/minimal)** | pkg-mgr base (`dnf`/`microdnf`) | glibc | Yes, redistributable | RHEL-lagged (no 3.14) | Version-lagged | The RHEL-shop option; Python tracks RHEL, so unfit for 3.14. |
| **Canonical Ubuntu Chiseled** | fixed/distroless | glibc | Yes | Ubuntu-release-tied | Bake-once only | Distroless slices of Ubuntu. |
| **SUSE BCI** | pkg-mgr base (`zypper`) | glibc | Yes | SLE-lagged | Version-lagged | Free SUSE base images. |
| **BellSoft Alpaquita** | pkg-mgr base | musl/glibc | Free tier | varies | Java-leaning | musl variant = the Python trap. |
| **Google Distroless** | fixed/distroless | glibc | Yes | Debian-lagged; experimental | Bake-once only | **Worst-CVE-of-three** (Debian-stable lag); Python is experimental. Rejected. |
| **Iron Bank (DoD P1)** | fixed | glibc | Free, access-gated | varies | Niche | For DoD supply chains. |
| **Stagex** | source-built | musl | Yes, OSS | limited catalog | Niche | Fully reproducible/bootstrappable; supply-chain purist option. |
| **Minimus / Echo / WizOS** | fixed | glibc | Commercial | varies | Commercial | Chainguard challengers; SLA + FIPS/STIG evidence. |

Sources: [RedMonk "Why Hardened Images are Suddenly Everywhere"](https://redmonk.com/kholterhoff/2026/06/01/why-hardened-images-are-suddenly-everywhere/),
[Free DHI challenges Chainguard (TechTarget)](https://www.techtarget.com/searchitoperations/news/366636656/Free-Docker-Hardened-Images-challenge-Chainguard),
[Red Hat UBI vs Hardened Images](https://developers.redhat.com/articles/2026/06/29/red-hat-ubi-vs-red-hat-hardened-images-how-to-choose),
[Distroless vs Chainguard vs Wolfi](https://safeguard.sh/resources/blog/distroless-vs-chainguard-vs-wolfi-base-images),
[Minimus: Chainguard alternatives](https://www.minimus.io/post/chainguard-alternatives-hardened-image-providers).

## Spike evidence (2026-07-09)

Real build of `cgr.dev/chainguard/wolfi-base` + `apk add python-3.14 git bash postgresql-client curl` + copied `uv`:

- **Python 3.14.6** present; git 2.55.0, bash 5.3.0, uv 0.11.26, pg_isready 18.4, curl 8.21 — all modern.
- TAP's **full dependency closure `uv sync`'d cleanly** (glibc manylinux wheels incl. native `rpds-py`, our `webauthn 3.0.0`; `django 6.0.2` imports). No source builds — the Alpine/musl trap avoided.
- **from-git plugin path works** (`git ls-remote` over TLS — DNS/TLS/git all functional).
- **Trivy OS-package CVEs: 0** (vs **311** on `python:3.14-slim`: 8 critical / 63 high / 122 medium / 118 low) — *with* git/bash/uv still installed.

Caveats: (1) `0` is *OS-package* CVEs at a moment in time — Python *dependency* CVEs are identical
on both bases (Renovate + Trivy-on-deps handle those). (2) It stays near-0 by *motion* (nightly
Wolfi rebuilds + our auto-patch loop), not magic. (3) `git` is present and CVE-prone, but Wolfi's
is current (2.55.0, 0 CVEs today) vs. Debian's lagged copy.

### Reproducing the spike

`Dockerfile` (two stages): `--target base` = `apk` binaries only (apples-to-apples OS-CVE scan
vs the current venv-less slim web image); `--target full` = `+ uv sync --frozen --no-install-project`
(proves the dep closure installs). Scan with Trivy via `ghcr.io/aquasecurity/trivy` (not Docker
Hub — avoids the 429): `trivy image --scanners vuln --pkg-types os --severity CRITICAL,HIGH,MEDIUM,LOW <img>`.

## Re-evaluation triggers

Revisit the provider choice — do **not** treat Wolfi as permanent — when any of these fire:

1. **We adopt the bake-once / distroless runtime variant.** Then a fixed hardened image becomes
   viable. **Benchmark free DHI `python` first** (Docker-native, Apache-2.0), then Google Distroless
   / Red Hat Hardened. The `req-cicd-base-image-lifecycle-4` off-ramps (drop git/curl) land here.
2. **A FIPS / FedRAMP / STIG requirement lands** (see below) — price Chainguard `python-fips` vs. the DIY path.
3. **We settle off bleeding-edge Python** (the version-lag filter stops mattering) — UBI / DHI / Chiseled re-open.

## The git-binary off-ramps

`git` is on the image solely so `uv` can install from-git plugins (uv shells out to the system
`git` binary; it does **not** bundle one). Two off-ramps, neither worth taking now (git = 0 CVEs on Wolfi):

- **(A) uv embedded git — passive.** [uv issue #12324](https://github.com/astral-sh/uv/issues/12324)
  tracks embedding a minimal git (likely [gitoxide](https://github.com/GitoxideLabs/gitoxide), the
  pure-Rust git already used by cargo/Helix). If it ships, delete `git` from the `apk` line — a free win. **Watch it.**
- **(B) archive-tarball plugin source — active, ours.** Replace `git+https://forge/org/repo@<sha>`
  with `https://forge/org/repo/archive/<sha>.tar.gz`. uv fetches it over **its own HTTPS client**
  (no `git`, and no `curl` either) and builds it; we verify against our own `sha256` pin (the same
  `tap/boot_records.py` `canonical_digest_bytes` pattern), which is *stronger* provenance than git's
  object hashing. Cost: a TAP-side `archive` source type in the boot `install` section. **Take it
  with the bake-once variant** — where dropping `git` + `curl` is a free byproduct and the end-state
  runtime minimum becomes `python + uv + app`.

## FIPS analysis: buy vs. DIY OpenSSL-3-FIPS

The question: TAP principally needs **Python executing FIPS-validated crypto**. Is there a shorter
path than buying a fully FIPS-validated image, using OpenSSL 3's modular FIPS provider?

### What FIPS actually requires

FIPS 140-3 compliance is not a flag — it's a **NIST CMVP-validated crypto *module*** (a specific
compiled build), operated **in FIPS mode**, within a defined **cryptographic boundary**, with
startup self-tests and approved-algorithms-only. Two very different bars hide under "FIPS":

- **"Use FIPS-validated crypto"** — a technical control. Achievable DIY.
- **"Be FIPS-certified / attested"** (FedRAMP, DoD) — an audit posture needing the module's CMVP
  cert, STIG evidence, SBOM/VEX for *your* platform. Usually wants the **vendor's** validated image.

### OpenSSL 3 FIPS provider state (2026)

OpenSSL 3 ships a **modular FIPS provider** (`fips.so`) loaded via `openssl.cnf` (provider-based,
not the legacy `FIPS_mode_set`). Validated modules:

- **#4282** — OpenSSL 3.0 FIPS provider (the upstream, self-buildable one; older crypto).
- **#4985 / #5102** — OpenSSL 3.1.2 FIPS Provider (Chainguard rebrand, no crypto changes, 2026-01-07).
- **#5132** — **OpenSSL 3.4.0** FIPS provider (Chainguard, 2026-03-17) — *the only 3.4-based module with FIPS 140-3 validation*.
- 3.6 (adds PQC: ML-KEM/ML-DSA/SLH-DSA/LMS) submitted, pending.

**The linchpin — why #4282 is sufficient, not a compromise.** OpenSSL guarantees a FIPS provider
from *any* certified release is **binary-compatible with any *later* libcrypto/libssl** — in their
own words, *"you can build OpenSSL 3.4 and use the OpenSSL 3.0.9 FIPS provider with it"*
([OpenSSL fips_module](https://docs.openssl.org/3.3/man7/fips_module/),
[README-FIPS](https://github.com/openssl/openssl/blob/master/README-FIPS.md)). So we build **only**
the frozen, validated **3.0.9 `fips.so`** (#4282 covers OpenSSL 3.0.8/3.0.9) and load it against the
base's **current, patched** libcrypto. OpenSSL 3.0's September-2026 LTS-EOL is therefore irrelevant —
the base libraries stay modern (CVEs outside the FIPS boundary keep getting fixed); only the validated
*provider* is frozen, which is the entire point of a validated module. Chainguard's newer validated
modules (3.1.2 #5102, 3.4 #5132, paid) are **not needed**. ([OpenSSL 3.0.9 FIPS validated](https://www.openssl.org/blog/blog/2024/01/23/fips-309/),
[CMVP #4282](https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/4282),
[140sp4282 security policy](https://csrc.nist.gov/CSRC/media/projects/cryptographic-module-validation-program/documents/security-policies/140sp4282.pdf)).

### TAP's crypto surface — the good news

Everything TAP does is **already FIPS-approved algorithms**, so *no crypto redesign* either path:

- passkey / `webauthn`: **ECDSA P-256, SHA-256** — approved.
- Django sessions/CSRF/passwords: **AES-GCM, HMAC, PBKDF2-SHA256** — approved.
- our digests/compares: **SHA-256, HMAC** — approved.
- `secrets`/`os.urandom` → kernel getrandom (entropy source; strict validation prefers a validated DRBG — a boundary detail, not an algorithm problem).

### The one real technical gotcha: `cryptography` bundles its own OpenSSL

The `cryptography` package (which `webauthn` uses) **statically bundles its own OpenSSL** in wheels —
so by default it does **not** use the system (FIPS) OpenSSL at all. To route it through a FIPS
module you must **rebuild it from source against the system OpenSSL**: `uv pip install cryptography
--no-binary cryptography`. That single rebuild is the whole DIY integration point (and a standing
maintenance cost on every `cryptography` bump). ([pyca/cryptography + system OpenSSL](https://cryptography.io/en/latest/installation/),
[Python + FIPS OpenSSL discussion](https://discuss.python.org/t/python-3-with-openssl-3-fips-enabled/20287)).

### The chosen recipe — self-built #4282 provider (web container)

> **Superseded as to the version (2026-09-02, decision D17 in [doc-fips-assessment-record.md](doc-fips-assessment-record.md)):** the recipe below stands, but the pin now tracks OpenSSL's FIPS code line at its patched releases and claims a certificate only when the pinned version carries one (derived from `docker/build-openssl-fips.sh`, `req-fips-pin-currency-8`). #4282 is FIPS 140-2 with sunset 2026-09-21; #4985 is the 3.1.2 module under 140-3.

Decided (`req-cicd-base-image-lifecycle-5`, targeted ~2026-09): DIY the free #4282 provider; no vendor
module. The mechanism, and why it's lighter than it first appears:

1. **Builder stage — build the validated provider.** Compile OpenSSL **3.0.9** with `./Configure
   enable-fips`, **following the #4282 security policy's exact build instructions** (the build recipe is
   part of what's validated). Output: `fips.so`.
2. **Activate it on the base's modern OpenSSL.** Place `fips.so` in the system `ossl-modules/` dir and run
   **`openssl fipsinstall`** — it runs the module self-tests and writes `fipsmodule.cnf` carrying the
   module's integrity **MAC**. This MUST run in the final image; if `fips.so`'s bytes change without
   re-running it, the provider refuses to load.
3. **Point OpenSSL at a FIPS config.** `openssl.cnf` → `.include fipsmodule.cnf`, activate the `fips` +
   `base` providers, `default_properties = fips=yes`; `ENV OPENSSL_CONF=/etc/ssl/openssl-fips.cnf`. The
   system OpenSSL now serves only FIPS-approved algorithms.
4. **Python stdlib is FIPS with NO rebuild.** Wolfi's `python-3.14` dynamically links the *system*
   libcrypto/libssl, so `hashlib`/`ssl`/`hmac` inherit the activated provider for free.
5. **`cryptography` is the one chore.** Its wheel statically bundles its own OpenSSL and ignores the
   system provider, so build it **`--no-binary cryptography`** against the system OpenSSL (uv:
   `[tool.uv] no-binary-package = ["cryptography"]`), baked at build time so the runtime carries no
   Rust/C toolchain. ([cryptography + system OpenSSL](https://cryptography.io/en/latest/installation/),
   [bundled-OpenSSL FIPS issue #5008](https://github.com/pyca/cryptography/issues/5008)).

Both Python stdlib crypto and `cryptography`/`webauthn` then route through the validated 3.0.9 module.
TAP's algorithms are all FIPS-approved, so nothing is redesigned.

### Postgres — minimal + the same FIPS recipe

Today's `postgres:16-alpine` is a needless CVE surface for a real-world posture (Alpine still ships an
`apk` package set; the official non-alpine image carries *hundreds* of packages). The consistent answer:
build a **minimal Postgres on `wolfi-base` + `apk add postgresql-16`** (mirrors the web image's model),
then apply the **identical #4282 recipe** — Postgres links the base's system OpenSSL for TLS + `pgcrypto`,
so the same `fips.so` + `fipsinstall` + `OPENSSL_CONF` makes it FIPS with no Postgres rebuild. One provider
artifact, one recipe, both containers, all free. (Chainguard's free `cgr.dev/chainguard/postgres` /
`-slim` is a zero-CVE alternative, but it's distroless — `COPY`-only, no `RUN` — so activating the provider
means a multi-stage copy-in; owning the `wolfi-base` + `apk` build keeps parity with the web image and the
same add-our-binaries model. Chainguard `postgres-fips` exists but is paid — not needed.)
([Chainguard postgres](https://images.chainguard.dev/directory/image/postgres/overview)).

### Named risks + status

Status: **active, targeted ~2026-09** (`req-cicd-base-image-lifecycle-5`). Three risks to work, none a blocker:

1. **Operational Environment (OE) portability.** #4282's security policy lists the *tested* platforms;
   Wolfi is almost certainly not one, so we rely on **FIPS 140-3 vendor-affirmed portability** (same CPU
   arch + glibc; we affirm correct operation). Common and widely accepted, but the **3PAO / compliance
   authority has final say** — confirm acceptance *before* building the recipe (this is the one thing that
   could force a validated-OE base or, last resort, a vendor's platform CMVP).
2. **`fips=yes` disables non-approved algorithms globally** (MD5, etc.). Audit Django/deps for any
   import-time non-approved primitive without `usedforsecurity=False` (modern Django is clean; verify with a script).
3. **`fipsinstall` in-image + reproducibility** — must run in the final build; the MAC pins the exact
   `fips.so`. Fits the build-stage model.

### Spike evidence — the full recipe is proven end-to-end (2026-07-09)

A dedicated FIPS spike (`spikes/fips/Dockerfile.fips`, three stages) ran the whole recipe on `wolfi-base`
and **every assertion passed**:

- **Builder** — OpenSSL **3.0.9** compiled with `./Configure enable-fips` on Wolfi → `fips.so` (#4282). Builds clean; retires "can we build the validated module ourselves."
- **Binary-compat linchpin (the load-bearing claim)** — Wolfi's *current* system OpenSSL **3.6.3** ran `openssl fipsinstall` against our frozen **3.0.9** `fips.so`: self-tests **passed**, integrity MAC written, `version: 3.0.9`. Modern libcrypto + frozen validated module is not just documented — it *works*. OpenSSL-3.0-LTS-EOL confirmed irrelevant.
- **Provider activation** — `openssl list -providers` → `fips 3.0.9 active` + `base active`; default provider gone. sha256 works; **md5 refused** (`evp_generic_fetch: unsupported`).
- **Python stdlib, ZERO rebuild** — Wolfi `python-3.14` (3.14.6) links system OpenSSL 3.6.3; `_hashlib.new("md5")` → `ValueError: unsupported`; sha256 works. FIPS enforcement reaches Python's crypto with no Python rebuild.
- **`cryptography` / `webauthn` engine (the TAP-specific proof)** — `cryptography 49.0.0` built `--no-binary` dynamically links system OpenSSL 3.6.3 (not its vendored static copy). **P-256 ECDSA sign+verify OK** (exactly the passkey-assertion verification), SHA-256 OK, **MD5 → `InternalError`** (FIPS provider refuses it).

### FIPS is on by default — and the non-approved-algorithm audit that makes that safe

`req-cicd-base-image-lifecycle-6` makes the recipe a build flag, `ARG TAP_FIPS` (**default `1`**),
on both web and DB images. `TAP_FIPS=0` is an explicitly-requested escape hatch, never a silent
fallback; `cryptography` is built `--no-binary` in **both** modes so only *provider activation*
differs; the image declares its mode machine-legibly (`org.tap.fips` OCI label + `TAP_FIPS_MODE`);
and a boot check must **prove** the declared mode (fips provider active **and** a non-approved
primitive actually refused) or emit `TAP-ABORT`. Assert, don't assume — the spike's first pass
"parsed" a config that activated nothing and silently ran the default provider.

Turning FIPS on globally disables non-approved algorithms, so "will anything break?" was answered
by measurement rather than hope (2026-07-09):

| Question | Answer |
| --- | --- |
| Does SHA-1 break? | **No.** SHA-1 is a FIPS-*approved* hash (restricted only for signature generation) and is served by the `fips` provider. |
| Does `uuid5` break? | **No** — and this was the real landmine: `uuid5` is SHA-1-based and TAP mints deterministic node/edge ids with it in **17 files**. CPython 3.14's `uuid5` passes `usedforsecurity=False`, and SHA-1 is approved anyway. |
| Does MD5 break? | **Yes**, `hashlib.md5()` → `UnsupportedDigestmodError`. But `hashlib.md5(usedforsecurity=False)` succeeds — served by `_hashlib` from a **separate non-FIPS `OSSL_LIB_CTX`** CPython keeps for non-security uses. |
| Does TAP use either? | **No.** Zero `md5`/`sha1`/`uuid3` in our code; only `hashlib.sha256` (13 sites) + `hmac.compare_digest` (2). |
| Do our deps? | Bare `md5()` only in Django's legacy `MD5PasswordHasher` (**not** in Django's default `PASSWORD_HASHERS`; TAP doesn't override them → unreachable) and `faker` (test-only). Bare `sha1()` in `cryptography`, `webauthn`, `oauthlib`, `django.template.loaders.cached` — all approved, all fine. **No runtime hard-fail surface.** |

Honest residuals: `usedforsecurity=False` is a *reachable* non-validated path (FIPS permits it for
non-security use, but don't imply it's absent), and `_blake2` remains a built-in non-validated
implementation. Re-run the sweep on dependency bumps — a new bare `md5()` in a runtime dep is a
boot-breaking regression under `TAP_FIPS=1`, which is precisely what the fail-closed boot check catches.

### Two gotchas the spike surfaced, now baked into the recipe

1. **`openssl.cnf` directive order is load-bearing.** `openssl_conf = openssl_init` MUST sit in the default (pre-section) block *before* `.include fipsmodule.cnf` — because that included file *starts* with `[fips_sect]`, so an `.include` placed first silently swallows `openssl_conf` into that section. Symptom: config "parses" with no error but **no providers activate** and OpenSSL falls back to the default provider (FIPS not enforced). Put `openssl_conf` first.
2. **`CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1` at build.** Keeps `cryptography` from loading OpenSSL's legacy provider, which would silently re-enable MD5/DES and defeat the enforcement. Set it (build- and run-time).

Net: the recipe is validated end-to-end at **$0 license** on the free upstream **#4282** certificate — no Chainguard OpenSSL module needed. What remains before ~2026-09 is *productionizing* (fold into the real Wolfi `Dockerfile` + `docker-compose` Postgres, `[tool.uv] no-binary-package = ["cryptography"]`, boot + full test-lane validation) and the **OE vendor-affirmation acceptance** conversation with the compliance authority (risk #1 above) — a paperwork/posture question, not a technical unknown.
