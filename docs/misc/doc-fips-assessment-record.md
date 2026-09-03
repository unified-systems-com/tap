---
spec: ../../specs/spec-fips.md
audience: [llm, developer, assessor]
covers:
  - ../../specs/spec-fips.md
  - req-fips-crypto-bom
  - ../../specs/spec-cicd-hardening.md
  - req-cicd-base-image-lifecycle-5
  - req-cicd-base-image-lifecycle-6
update-triggers:
  - The FIPS recipe is productionized into the real Dockerfile / docker-compose
  - A dependency bump introduces a bare hashlib.md5() in a runtime dependency
  - The compliance authority rules on vendor-affirmed Operational Environment portability
  - OpenSSL publishes a newer free/upstream validated FIPS provider (add it to OSSL_CMVP_VALIDATED; D17 reversal trigger)
  - The OpenSSL FIPS provider pin moves (re-run the per-CVE triage; the fips-claims guard names every stale claim)
  - The base image changes away from Wolfi
  - django-allauth or PyJWT is upgraded (re-audit the OIDC algorithm surface, sec 5.2)
  - TAP_FIPS=1 goes live (build the OIDC crypto-error rescue designed in sec 5.3)
assumes:
  - Reader may be an AI assistant validating or extending TAP's FIPS posture
  - Wolfi is the standard base (req-cicd-base-image-lifecycle-3)
provides: |
  The complete FIPS decision record, lessons learned, assessment methodology, and a
  re-runnable verification suite for TAP's self-built OpenSSL 3.0 #4282 FIPS provider.
  Written as a handoff artifact: an AI (or human) assessor should be able to validate
  the implementation, or resume the assessment, using only this document plus spikes/.
---

# TAP FIPS Assessment Record

**Authoritative spec:** [spec-fips.md](../../specs/spec-fips.md) — the FIPS center of gravity (the
behavioral contract + the FIPS Requirement Map). **This doc is the detailed, measurement-backed
decision record** the spec references: read the spec for *what* TAP guarantees, read this for *why*,
*how it was proven*, and *how to re-verify it*.

**Status:** recipe spike-proven (2026-07-09); **web + DB productionized 2026-07-21** (`TAP_FIPS=1` default).
**Requirements:** `req-fips-crypto-bom` family (spec-fips.md); `req-cicd-base-image-lifecycle-5` (the recipe),
`-6` (the build flag, default ON) in spec-cicd-hardening.md.
**Executable evidence:** `spikes/fips/` and `spikes/distroless/`.

## 0. How to use this document

If you are an **AI assistant** asked to validate, extend, or productionize TAP's FIPS posture:

1. Read §1 (what FIPS means here) so you don't conflate the two very different bars.
2. Read §2 (decisions) — these are settled; do not silently re-litigate them. Each carries its
   reversal trigger.
3. Read §4 (lessons) **before writing any code**. Several are fail-*open* traps: the system looks
   compliant while enforcing nothing. They cost real debugging and will recur.
4. Run §6 (the verification suite) to establish ground truth on the current image. **Do not trust
   this document's measurements over a fresh run** — they were true on 2026-07-09 against specific
   image digests, and base images move.
5. Consult §7 for the risk register. §7.1 is **accepted and owned** (not a blocker); §7.2–7.5 are genuinely open — do not report those as closed.

**If you are debugging a crypto error that only happens under FIPS, jump straight to §5.3.**

If you are a **human**: §1, §2, §4, and §7 are the substance. §3 is the recipe, §6 is how to check it.

The governing principle throughout, from `specs/spec-security-posture.md`:

> **Assert, don't assume.** A configuration that "parses cleanly" is not a configuration that
> *took effect*. Every FIPS claim in this document is backed by a negative control — proof that a
> non-approved primitive is actually *refused* — not merely by the absence of an error.

## 1. What "FIPS" actually means here (two different bars)

FIPS 140-3 compliance is not a flag. It is a **NIST CMVP-validated cryptographic *module*** (a
specific compiled artifact), operated **in FIPS mode**, inside a defined **cryptographic boundary**,
with power-on self-tests and approved-algorithms-only. Two very different bars hide under the word:

| Bar | What it means | Achievable by us? |
| --- | --- | --- |
| **"Use FIPS-validated crypto"** | A technical control: crypto operations execute inside a validated module. | **Yes, DIY.** This is what we built and proved. |
| **"Be a FIPS-certified platform"** | An audit posture (FedRAMP, DoD): the module's CMVP certificate covers *your* Operational Environment, and a 3PAO signs off. | Partly. Depends on the OE question — see §7.1. |

TAP targets the first bar in its D17 form (FIPS mode on a patched build of the validated code line, the certificate claimed only when the pinned version actually carries one) and defers the second — the re-pin path is one table entry away. **When someone says "we need FIPS,"
find out which bar they mean before designing anything.** The answer changes the base image.

### The relevant CMVP certificates

- **#4282** — OpenSSL 3.0 FIPS Provider (covers OpenSSL 3.0.8 / 3.0.9). FIPS 140-2, Active, **sunset 2026-09-21** (observed 2026-09-02). **Free, upstream, self-buildable.** ← the version TAP pinned until D17; the pin now tracks the patched code line (D17), and the table of validated versions lives in `docker/build-openssl-fips.sh` (`OSSL_CMVP_VALIDATED`), where the derived posture reads it.
- **#4985** — OpenSSL 3.1.2 FIPS Provider (OpenSSL's own certificate). FIPS 140-3 level 1, Active, sunset 2030-03-10. Free, upstream, self-buildable — the re-pin target if an audit needs a 140-3 certificate (still carries CVE-2026-31790 and CVE-2026-42770 inside the module).
- **#5102** — OpenSSL 3.1.2 FIPS Provider (Chainguard rebrand of the same module). Paid. Not needed.
- **#5132** — OpenSSL 3.4.0 FIPS Provider (Chainguard). Paid. Not needed.

## 2. Decisions (settled — each with its reversal trigger)

| # | Decision | Rationale | Reverses if… |
| --- | --- | --- | --- |
| D1 | **FIPS is a hard requirement**, targeted ~2026-09; not demand-gated. | Frontlined by George, 2026-07-09. | — |
| D2 | Use the **free upstream OpenSSL 3.0 #4282** provider. No vendor/Chainguard module. | #4282 is sufficient and costs $0. Vendor modules buy nothing we need. | A 3PAO requires a module whose CMVP certificate covers a *tested* OE → §7.1 ladder rung 1 (buy the same-family validated image). **Risk accepted + owned; not blocking.** |
| D3 | **Build `fips.so` ourselves** in a builder stage, per the #4282 security policy's build instructions. | The build recipe is part of what is validated. | — |
| D4 | Run the **frozen 3.0.9 `fips.so` against the base's modern libcrypto.** | OpenSSL guarantees a certified `fips.so` is binary-compatible with **any later** libcrypto. Verified: Wolfi's OpenSSL **3.6.3** `fipsinstall`ed and self-tested our 3.0.9 module. **Therefore OpenSSL 3.0's Sept-2026 LTS-EOL is irrelevant** — base libs stay patched; only the validated module is frozen. | OpenSSL revokes the compatibility guarantee. |
| D5 | Activate via **`openssl fipsinstall` in-image** + an `openssl.cnf` + `ENV OPENSSL_CONF`. | `fipsinstall` runs self-tests and writes the module's integrity **MAC**. It must run in the final image; if `fips.so`'s bytes change without re-running it, the provider refuses to load. | — |
| D6 | **Strict provider set: `fips` + `base` only. No `default` provider.** | Loading `default` would silently re-supply every non-approved algorithm. **The `default` provider is built into `libcrypto`, not a file** — so the boundary is the *config*, not the modules directory (L13). `base` adds **no crypto primitives** (encoders/decoders only): dropping it blocks no MD5 and breaks OpenSSL key-file I/O, so `fips`+`base` is correct rather than `fips` alone (L15). Verified: TLS 1.3 still negotiates and `openssl req` still signs P-256 with the strict set. | Never, for convenience. Only if an unavoidable non-security consumer cannot use `usedforsecurity=False`. |
| D7 | Build **`cryptography` `--no-binary`** against the system OpenSSL — **in both FIPS and non-FIPS modes.** | Its wheel *statically bundles its own OpenSSL* and would bypass the system FIPS provider entirely. Building it the same way in both modes means only *provider activation* differs; otherwise non-FIPS passes on a bundled wheel and FIPS breaks at the far end of the pipeline. | — |
| D8 | Set **`CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1`**. | Otherwise `cryptography` loads OpenSSL's legacy provider, silently re-enabling MD5/DES. | — |
| D9 | **No Python rebuild.** | Wolfi's `python-3.14` dynamically links the *system* libcrypto, so `hashlib`/`ssl`/`hmac` inherit the activated provider for free. Verified. | The base ships a statically-linked or vendored-OpenSSL Python. |
| D10 | **Postgres gets the identical recipe** on a minimal `wolfi-base` + `apk postgresql-16`. | Postgres links the system OpenSSL for TLS + `pgcrypto`. One provider artifact, one recipe, both containers. | — |
| D11 | **Wolfi is the standard base**; in-image FIPS chosen over RHEL's host-derived FIPS. | We ship a self-hosted product onto **customer-controlled hosts**. An in-image FIPS container is FIPS anywhere. A RHEL container **cannot enable FIPS by itself** (L10). Staying in the Wolfi family also makes the OE fallback a *base-image swap, not a rewrite* (§7.1). | Compliance rejects vendor-affirmed OE → escalate the §7.1 ladder (Chainguard validated-FIPS image first; UBI + FIPS-mode hosts last). |
| D12 | **`ARG TAP_FIPS`, default `1`.** FIPS-on is the published artifact. | Secure by default. | — |
| D13 | `TAP_FIPS=0` is an **explicitly-requested escape hatch, never a silent fallback.** CI builds and gates both variants so the non-FIPS lane cannot rot. | — | — |
| D14 | The image **declares its mode machine-legibly**: OCI label `org.tap.fips=true\|false` + `ENV TAP_FIPS_MODE`. | CI, the boot record, `/healthz`, and an AI operator can read posture **without executing crypto** (`specs/spec-ai-integration.md`). | — |
| D15 | **Boot must PROVE the declared mode** (fips provider active **and** a non-approved primitive actually refused) or emit `TAP-ABORT` and refuse to serve. | Fail closed. See L1 — a config can parse cleanly and enforce nothing. | Never. |
| D16 | **Alternatives are parked, not eliminated**, with named reopen triggers. | The distroless bases work (proven); they lost on Python currency + FIPS model, not on capability. | §7.1, bake-once adoption, or Wolfi regression. |
| D17 | **Patch currency outranks the certificate: the provider pin tracks OpenSSL's FIPS code line at its patched releases, and the shipped artifact is declared "FIPS mode on, approved-algorithms-only, NOT CMVP-validated as shipped" whenever the pinned version carries no certificate.** The 2026-08-31 ruling ("a secure OpenSSL matters more than a FIPS-validated one") is read *literally*, not exposure-weighted. First application: the move 3.0.9 (#4282) → 3.0.22 under the exit ramp (George, 2026-09-02, unified-systems-com/tap#295), landed as its own PR on top of this record (unified-systems-com/tap#307) so the move can never ship ahead of its justification — this entry records the decision; the pin itself moves there. | Three sentences. **Validation freezes the module** — a certificate is of one build, so "validated" and "currently patched" are mutually exclusive properties of the same artifact. **Patch currency is the property this project will not give up** — shipping a crypto provider with known unfixed flaws to keep a certificate is not a position TAP takes. **The boundary design makes the trade cheap** — the module is algorithms-only (D4: a frozen `fips.so` beside the base image's modern libcrypto), so of the 46 CVEs Grype matched against 3.0.9 the libcrypto/libssl beside it already carried 41; only 5 sat inside the module, and today none is on a path TAP exercises. *Why literal rather than exposure-weighted:* "nothing reaches the five" is today's exposure only — the ECDSA signing timing flaw (CVE-2024-13176) becomes reachable the moment TAP signs in-process, and a sigstore plugin exists; a rule that re-litigates exposure per CVE is a rule that lets the lie ship first. **Evidence exhibit:** [doc-fips-provider-cve-triage-2026-09.md](doc-fips-provider-cve-triage-2026-09.md) — the per-CVE boundary table (5 inside / 41 outside / 0 not determinable, each with OpenSSL's own advisory sentence or binary evidence) is the standing pattern for every future bump (`req-fips-pin-currency-7`). *Also observed 2026-09-02:* #4282 is FIPS 140-2 with **sunset 2026-09-21**, so the certificate was leaving on its own within three weeks. **Consequences:** the "validated" claim is no longer written anywhere — it is derived from the pin by `tap.fips_pins` (crypto-BOM state `FIPS_MODE_UNVALIDATED_BUILD`, SBOM `tap:fips-validation`, README status clause, fips-claims guard; `req-fips-pin-currency-8`). D2's "free upstream #4282" and D4's "frozen 3.0.9" are superseded as to the *version*; their recipe (self-built free provider, frozen `fips.so` against modern libcrypto) stands. | **An audit that needs the certificate** — then re-pin, for that build, to a version in the `OSSL_CMVP_VALIDATED` table (3.0.9/#4282 or 3.1.2/#4985; the latter is 140-3 and does not clear CVE-2026-31790 / CVE-2026-42770) via the `bump-openssl-fips` skill; the derived posture flips back to validated with no prose to fix. Or: OpenSSL validates a current release (the table gains an entry and the pin can sit on it). |

## 3. The proven recipe

Five steps. Reproducible via `spikes/fips/Dockerfile.fips` (three stages, all green).

1. **Builder stage — build the validated provider.** Compile OpenSSL **3.0.9** with
   `./Configure enable-fips && make && make install_fips`. Output: `fips.so`.
2. **Drop it into the runtime base's `ossl-modules/` dir**, then run
   `openssl fipsinstall -out /etc/ssl/fipsmodule.cnf -module /usr/lib/ossl-modules/fips.so`.
   This runs the module self-tests and writes the integrity MAC. **Must happen in the final image.**
3. **Point OpenSSL at a FIPS config** and export `OPENSSL_CONF`. Exact content, **ordering is
   load-bearing** (see L1):

   ```ini
   config_diagnostics = 1
   openssl_conf = openssl_init

   .include /etc/ssl/fipsmodule.cnf
   .include /etc/ssl/ca.cnf          # restore the stock openssl.cnf include we displace

   [openssl_init]
   providers = provider_sect
   alg_section = algorithm_sect

   [provider_sect]
   fips = fips_sect
   base = base_sect

   [base_sect]
   activate = 1

   [algorithm_sect]
   default_properties = fips=yes
   ```

4. **Python stdlib inherits it with no rebuild.** `hashlib`, `ssl`, `hmac` route through the
   activated provider because Wolfi's CPython dynamically links the system libcrypto.
5. **Build `cryptography` `--no-binary`** against the system OpenSSL, with
   `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1`, baked at build time (so the runtime carries no Rust/C
   toolchain). In uv: `[tool.uv] no-binary-package = ["cryptography"]`.

Both Python stdlib crypto and `cryptography`/`webauthn` then execute inside the validated 3.0.9
module. **TAP's algorithms are all FIPS-approved** (P-256/ECDSA, SHA-256, HMAC, PBKDF2, AES-GCM),
so nothing is redesigned.

## 4. Lessons learned

Ordered by how badly each will bite you. **L1, L2, and L5 are fail-*open*: the system appears
compliant while enforcing nothing.** These are the dangerous ones.

### L1 — `openssl.cnf` directive order silently disables FIPS entirely ⚠️ FAIL-OPEN

**Symptom:** Config parses with no error. `openssl list -providers` shows only *"OpenSSL Default
Provider"*. `md5` succeeds. FIPS is not enforced anywhere, including in Python.

**Root cause:** `openssl_conf = openssl_init` must live in the **default (pre-section) block**. The
`.include /etc/ssl/fipsmodule.cnf` pulls in a file that **starts with `[fips_sect]`** — so if the
`.include` comes first, every subsequent directive (including `openssl_conf`) is parsed as belonging
to `[fips_sect]`. OpenSSL never sees a global `openssl_conf`, ignores the provider config, and falls
back to its built-in default provider.

**Fix:** `openssl_conf` first, `.include` after. See §3 step 3.

**Detection:** Never conclude FIPS is on because the build succeeded. Assert
`openssl list -providers` contains `fips` **and** that `md5` is refused.

### L2 — Hand-rolling a shared-library closure with `ldd` fails open on Wolfi ⚠️ FAIL-OPEN

**Symptom:** A staged rootfs looks complete; binaries mysteriously fail at runtime with
`error while loading shared libraries: libpcre2-8.so.0`.

**Root cause:** **Wolfi ships no `ldd` binary.** A staging script of the shape
`ldd "$bin" 2>/dev/null | ... || true` copies **zero** libraries and reports success. Some binaries
still work because their libs happen to exist in the base — masking the bug.

**Fix:** Never hand-roll the closure. Use the package manager's own install-into-a-root flow:
`apk add --root /rootfs --initdb` (Wolfi) or `dnf install --installroot=/rootfs` (Red Hat). These
resolve the dependency closure correctly by construction.

**Meta-lesson:** `2>/dev/null || true` around a *discovery* step converts a hard failure into a
silent wrong answer. Never suppress errors on a step whose output you then trust.

### L3 — `git` is not one binary; its porcelain are shell scripts

**Symptom:** `git ls-remote` works; `uv pip install git+https://…` dies with `sed: command not found`.

**Root cause:** Helpers in `/usr/libexec/git-core` (`git-submodule`, `git-sh-setup`, …) are **shell
scripts** that shell out to `sed`/`grep`. `uv`'s git install runs `git submodule update --init`.

**Fix:** A minimal image carrying `git` must also carry `sed`, `grep`, `coreutils`. These are now
named as non-optional in `req-cicd-base-image-lifecycle-3`.

### L4 — `/bin`, `/sbin`, `/lib`, `/lib64` are symlinks into `/usr/`

**Symptom:** `COPY --from=builder /rootfs /` fails with `cannot copy to non-directory: …/bin`.

**Root cause:** Distroless bases (Chainguard, and RHEL's usr-merge) symlink these into `/usr/`. A
staged rootfs that materializes them as real directories cannot overlay a symlink.

**Fix:** Merge staged content into the real `/usr/bin`, `/usr/lib` before the `COPY`.

### L5 — `hashlib.md5` has a builtin fallback that masks non-enforcement ⚠️ FAIL-OPEN (in tests)

**Symptom:** You "prove" FIPS blocks MD5 in Python via `hashlib.md5()`. On a different base it
passes even with FIPS off, because CPython falls back to a built-in `_md5`.

**Root cause:** `hashlib` is a façade. It prefers `_hashlib` (OpenSSL) but can fall back to
compiled-in `_md5`/`_sha1`/`_sha2` modules.

**Fix:** Probe the **lowest layer that cannot fall back**: `_hashlib.new("md5", b"x")`. On Wolfi's
CPython the builtins `_md5`/`_sha1`/`_sha2`/`_sha3` are **absent** (verified), so `hashlib.sha256`
genuinely is `_hashlib`-backed — but do not rely on that on another base. Assert the module:
`type(hashlib.sha256()).__module__ == "_hashlib"`.

### L6 — SHA-1 is FIPS-**approved**. Do not assume "not SHA-256 ⇒ banned."

SHA-1 is an approved hash under FIPS 140-3 (restricted only for *signature generation*). It is
served by the `fips` provider. `hashlib.sha1()` works under FIPS. **Only MD5 hard-fails** among the
common hashes. Auditing for "any non-SHA-256 hash" produces a large false-positive list.

### L7 — `uuid5` is SHA-1 and `uuid3` is MD5: crypto hides in the stdlib

This was the **real landmine**. TAP mints deterministic node/edge ids with `uuid5` in **17 files**.
Had `uuid5` broken, FIPS-default-on would have bricked boot.

It is **safe**, for two independent reasons: SHA-1 is approved (L6), *and* CPython 3.14's `uuid5`
passes `usedforsecurity=False` internally. Verified directly.

**Generalize this:** grep for `hashlib`/`hmac` is *not* a sufficient crypto audit. Hashing hides in
`uuid3`/`uuid5`, cache-key derivation, ETag generation, template fragment keys, and DB index-name
digests. Enumerate the *primitives reached*, not the *call sites named*.

### L8 — `usedforsecurity=False` reaches MD5 via a separate non-FIPS library context

`hashlib.md5(b"x", usedforsecurity=False)` **succeeds** under a strict `fips`+`base` provider set,
and is served by `_hashlib` (OpenSSL) — *not* a Python builtin (which doesn't exist on Wolfi).
CPython maintains a **separate non-FIPS `OSSL_LIB_CTX`** for exactly this purpose.

FIPS 140-3 **permits** non-approved algorithms for non-security purposes, and `usedforsecurity=False`
is the auditor-recognized signal. This is legitimate — **but it is a reachable, non-validated path.**
Name it in the risk register; do not imply MD5 is absent from the process.

### L9 — `cryptography`'s wheel bundles its own OpenSSL

The single biggest integration trap for a Python FIPS story. `pip install cryptography` gives you a
wheel with a **statically linked, private OpenSSL** that ignores the system provider config entirely.
Everything else can be perfectly configured and `webauthn` will still not be doing FIPS crypto.
`--no-binary cryptography` is mandatory (D7).

### L10 — Vendors implement FIPS in incompatible ways: **in-image vs host-derived**

The discovery that decided the base image.

- **Upstream OpenSSL (Wolfi):** `openssl fipsinstall` works. FIPS is configured **in the image** and
  is **host-independent**. A container we ship is FIPS anywhere.
- **Red Hat (UBI):** `openssl fipsinstall` is **deliberately disabled** —
  *"This command is not enabled in the Red Hat Enterprise Linux OpenSSL build."* RH ships
  `/usr/lib64/ossl-modules/fips.so` but **no `fipsmodule.cnf`**; `openssl.cnf` defers to
  `/etc/crypto-policies/back-ends/opensslcnf.config`, and the container inherits FIPS from the
  **host kernel** (`fips=1`, `/proc/sys/crypto/fips_enabled`).

**The trade:** RHEL 9 *is* a CMVP-**tested** OE for Red Hat's validated module, which would resolve
our OE risk (§7.1). But a RHEL container **cannot turn FIPS on by itself** — fatal when you don't
control the customer's host. Hence D11.

**Check `openssl fipsinstall` availability on any candidate base, early.** It tells you which model
you're in, in one command.

### L13 — An empty `ossl-modules/` does **NOT** mean only FIPS can do crypto ⚠️ FAIL-OPEN reasoning

**The tempting inference:** `/usr/lib/ossl-modules/` contains only `fips.so`, therefore no other
module can perform crypto operations. **This is false, and an assessor will catch it.**

In OpenSSL 3 the **`default` and `base` providers are compiled into `libcrypto` itself.** They are
not `.so` files. Only `fips.so` and `legacy.so` ship as separately-loadable modules. Proof, on our
own image:

- `ls /usr/lib/ossl-modules/` → `fips.so`, and nothing else.
- `find / -name '*.so*' | grep -E '/(default|base|legacy)\.so'` → **no matches.**
- Yet `openssl list -providers` reports **`base`, version 3.6.3, active.** It has no file.
- Neutralise *only the config*, same filesystem:
  `OPENSSL_CONF=/dev/null openssl list -providers` → **"OpenSSL Default Provider 3.6.3, active"**,
  and `openssl dgst -md5` **works**.

**The FIPS boundary is enforced by the configuration** (`default_properties = fips=yes`, plus not
activating `default`), **not by the contents of the modules directory.** This is also precisely how
CPython reaches MD5 under `usedforsecurity=False` (L8): it creates a second `OSSL_LIB_CTX` that
loads the built-in default provider — no file needed.

**Consequences:**
- Never cite the modules-directory listing as evidence of the cryptographic boundary.
- The config **is** the boundary, so it is integrity-critical: anything that can set `OPENSSL_CONF`,
  or write the file it points at, can silently disable FIPS. Treat both as protected assets.
- This is exactly why the fail-closed boot assertion (D15) must *execute crypto and observe a
  refusal*, rather than inspect files or parse config.

### L15 — `base` supplies **no cryptographic algorithms**; it is not a hole in the boundary

A natural follow-on to L13: *"if `default` is what serves MD5, and `base` is also active, wouldn't
dropping `base` tighten the boundary?"* **No.** Measured on our image, `fips`-only vs `fips`+`base`:

| | `fips` + `base` (shipped) | `fips` only |
| --- | --- | --- |
| `md5(usedforsecurity=False)` | works | **still works** (built-in `default`, separate libctx — L8) |
| `md5()` for security use | refused | refused |
| `sha256` | works (fips) | works (fips) |
| OpenSSL encoders available | **232** | **1** |
| `openssl` write/read a PEM key, `openssl req` | OK | **fails** (`unable to write elliptic curve parameters`) |

`base` provides **encoders, decoders and serializers** (PEM/DER key + certificate handling) and
**zero crypto primitives**. Removing it therefore removes no algorithm from reach, blocks no MD5,
and breaks OpenSSL key-file I/O. Keeping it is correct, and is the direct justification for D6's
`fips` + `base` set rather than `fips` alone.

Note also (measured, and contrary to the obvious guess): **`cryptography` does not need `base`** — it
serializes PEM in its own Rust ASN.1 code and never calls OpenSSL's encoders. Only the OpenSSL CLI
path depends on it.

### L14 — Overriding `OPENSSL_CONF` displaces the stock config, includes and all

Pointing `OPENSSL_CONF` at our own file means the base image's `/etc/ssl/openssl.cnf` is **not read**
— including its `.include /etc/ssl/ca.cnf`. On Wolfi, `ca.cnf` defines `[ca]`/`[CA_default]`/`[req]`
for the `openssl ca` / `openssl req` **CLI subcommands** (certificate issuance).

TLS **trust** is unaffected — that comes from `/etc/ssl/cert.pem` + `/etc/ssl/certs`, verified: 145
CA certs load and a real TLS 1.3 handshake succeeds under FIPS. But dropping it is a **latent trap**:
a future `openssl req` fails on a missing section, with a non-obvious cause. Fixed by re-adding
`.include /etc/ssl/ca.cnf`; verified this restores `openssl req` (P-256 CSR, `ecdsa-with-SHA256`)
**without** widening the provider set — `fips`+`base` only, md5 still refused.

### L16 — `fips=yes` restricts you to the **module**, not to the module's **approved subset**

Setting `default_properties = fips=yes` means "only fetch algorithms from a provider advertising
`fips=yes`". It does **not** mean "only FIPS-approved algorithms." A validated module may expose
services its CMVP security policy does not list as approved, and FIPS 140-3 permits this.

Measured on our self-built 3.0.9 module, with only `fips` + `base` active:

- `openssl list -signature-algorithms -verbose` attributes **`ED25519`, `ED448` and `DSA` to `@ fips`.**
  All satisfy an explicit `-propquery fips=yes`.
- **DSA signature *generation* is disallowed** under SP 800-131A, yet the module signs with it.
- `fipsmodule.cnf` carries a `dsa-sign-disabled` knob — **inert on a 3.0.9 module.** Setting it to `1`
  and re-running: DSA signing still **ALLOWED**. Those knobs (`hmac-key-check`, `no-short-mac`,
  `signature-digest-check`, `tdes-encrypt-disabled`, …) are 3.1+/3.4+ features written into the file
  by the *host's* newer `fipsinstall` (3.6.3 here) and ignored by the older validated module.
- There is **no EdDSA knob at all** (`grep -ci ed25519 fipsmodule.cnf` → 0), so no config lever exists
  to narrow it.

**Corrections to earlier claims in this document's own history:** (a) it was asserted that Ed25519 is
absent from the #4282 module — **false**, it is present and `fips=yes`. (b) **FIPS 186-5 (Feb 2023)
approves EdDSA** (Ed25519/Ed448), so its presence is not itself a finding. The durable lesson is the
general one: *presence + `fips=yes` ≠ listed as an approved service on the certificate.* The
authoritative source is the **#4282 security policy's Approved Algorithms table and its CAVP
certificates** — check there, not against the module's advertised algorithm list.

Practically irrelevant for TAP (we use P-256/ECDSA, SHA-256, HMAC, PBKDF2, AES-GCM), but an assessor
will probe exactly this, and "we set `fips=yes`" is not a sufficient answer.

### L11 — Ecosystem facts we got wrong until we measured them

Every one of these was asserted confidently (by me, or by a research pass) and was **false**:

| Claim | Reality (measured 2026-07-09) |
| --- | --- |
| "TAP's runtime install requires a package manager in the runtime image." | False. `uv sync` / `uv pip install git+…` are *Python-package* ops. Proven: a runtime with no `apk`/`apt` and **no `/bin/sh`** does both. |
| "RHEL caps at Python 3.12." | False. `dnf install python3.14` on UBI9 → **3.14.5**. |
| "Google Distroless ships Python 3.14." | False. `python3-debian13` → **3.13.5**. (The 3.11.2 I first measured was the *deprecated* debian12 line.) |
| "DHI is at some `docker.io` namespace." | False. It is **`dhi.io`**, and anonymous pull returns **HTTP 401**. |
| "Fixed/distroless images can't have packages added." | False. Every one supports build-time addition (`apk --root`, `dnf --installroot`, multi-stage `COPY`, apko, Nix). |

### L12 — Verify you are reading the *right* exit code

A background build wrapper reported `exit 0` because the last command in the pipeline was `tail`.
The build had actually **failed**. Use `set -o pipefail`, capture `$?` immediately after the command
under test, and print it explicitly. An assessment harness that lies about pass/fail is worse than none.

### L17 — `OPENSSL_CONF` is process-global: a bundled-OpenSSL dependency is a FIPS hard-fail ⚠️

Found at productionization (2026-07-21), not in the spike — because the spike never booted Django
against a real Postgres, and the §5 audit enumerated *hashing* call sites, not *transitive deps
that carry their own OpenSSL*.

`OPENSSL_CONF` is read by **every** OpenSSL instance in the process, including one **statically
bundled inside a wheel**. So the moment we set `ENV OPENSSL_CONF=…fips.cnf`, a dependency shipping
its own OpenSSL is *also* told to load the FIPS config — but it has no matching `fips.so` and its
bytes do not match our `fipsmodule.cnf` MAC, so provider activation fails and even basic RNG
breaks. `psycopg[binary]` (private bundled libpq + OpenSSL) hit exactly this: SCRAM-SHA-256 login
computes a client nonce via OpenSSL RAND, which failed with
`psycopg.OperationalError: could not generate nonce` — **the web container could not connect to the
database at all under FIPS.** Verified: `env -u OPENSSL_CONF` made the same connection succeed;
`PSYCOPG_IMPL=python` over the *system* libpq succeeded *with* the FIPS config.

**The fix is the same shape as L9/D7** (`cryptography --no-binary`): make the dependency use the
**system** OpenSSL, not a bundled one. For psycopg that is the **`[c]` extra** (`psycopg[c]`), which
builds the C speedups against the system libpq (needs `pg_config` + libpq headers — `postgresql-dev`
on Wolfi). The pure-Python `psycopg` over system libpq also works but is slower on the DB-bound test
lane.

**Generalize:** the FIPS audit is not "grep for md5". It is *"enumerate every dependency that links or
bundles OpenSSL and confirm it uses the system library."* A bundled-OpenSSL dep does not silently
bypass FIPS — thanks to the global `OPENSSL_CONF` it fails **loudly** — but "loudly" means *at boot,
in a place the hashing audit never looked.* The fail-closed boot self-check (D15) and the DB `connect`
health probe are the backstops that turn a future regression of this class into an immediate,
explained boot failure rather than a mystery.

## 5. TAP's actual crypto surface (audit result, 2026-07-09; psycopg addendum 2026-07-21)

| Surface | Finding |
| --- | --- |
| **TAP's own code** | Clean. **Zero** `md5`, **zero** `sha1`, **zero** `uuid3`. Only `hashlib.sha256` (13 call sites) and `hmac.compare_digest` (2). |
| **`uuid5`** | 17 files (collectors, `identity_core`, `github_core`, `samsite`, `fedramp_20x_ksi`). SHA-1-based. **Safe** (L7). |
| **Django** | Bare `hashlib.md5()` exists **only** in the legacy `MD5PasswordHasher`, which is **not** in Django's default `PASSWORD_HASHERS`, and TAP does not override them → **unreachable**. |
| **`faker`** | Bare `md5()`/`sha1()` — **test-only** dependency. |
| **`cryptography`, `webauthn`, `oauthlib`, `django.template.loaders.cached`** | Bare `sha1()` — approved, all work. |
| **`psycopg[binary]`** ⚠️ | **The one real hard-fail found at productionization** (this audit missed it — it looked only at *hashing*, not at *bundled-OpenSSL transitive deps*). `psycopg[binary]` ships a **private bundled libpq + OpenSSL**. `OPENSSL_CONF` is **process-global**, so that bundled OpenSSL is *also* forced to load our FIPS config, cannot satisfy the `fipsmodule.cnf` MAC (it is not our system OpenSSL, and has no matching `fips.so`), and **SCRAM-SHA-256 auth hard-fails at boot** with `psycopg.OperationalError: could not generate nonce` (the SCRAM client nonce is an OpenSSL RAND draw). **Fixed** by switching to **`psycopg[c]`** (builds against the *system* libpq → the system OpenSSL/FIPS provider → the validated DRBG generates the nonce). This is the exact psycopg analog of the `cryptography --no-binary` fix (L9). See **L17**. |
| **Verdict** | TAP's *hashing* surface has no runtime hard-fail (the original finding stands). But **any dependency that bundles its own OpenSSL is a hard-fail surface under FIPS**, because `OPENSSL_CONF` reaches it too — `psycopg[binary]` was one and is now `psycopg[c]`. `TAP_FIPS=1` by default is safe **with that fix in place**, and the fail-closed boot self-check (`tap.fips`, D15) plus the DB `connect` health probe now catch a regression of this class at boot. |

TAP's algorithms — P-256/ECDSA (passkeys), SHA-256, HMAC, PBKDF2, AES-GCM — are **all
FIPS-approved**. No crypto redesign is required by FIPS.

### 5.1 What depends on the `default` provider (and therefore loads it at runtime)

Our config never activates `default`. It is nonetheless **loaded lazily, in a separate
`OSSL_LIB_CTX`**, by any caller asking for a non-approved primitive with `usedforsecurity=False`
(L8). Seven such sites exist in the installed closure; **exactly one is reached by TAP**:

| Site | Reached? | Why |
| --- | --- | --- |
| `django/db/backends/utils.py:names_digest()` — `md5(usedforsecurity=False)` | **YES — on every boot** | Shortens index/constraint names; runs during `migrate`. |
| `django/utils/cache.py` `_generate_etag` / `_generate_cache_key` | no | No `ConditionalGetMiddleware`; no `@cache_page`. |
| `django/contrib/staticfiles/storage.py` | no | Not using `ManifestStaticFilesStorage`. |
| `django/core/cache/backends/filebased.py` | no | We use `DatabaseCache`. |
| `django/core/cache/utils.py` `make_template_fragment_key` | no | No `{% cache %}` template tag. |
| `requests/auth.py` (HTTP Digest) | no | `HTTPDigestAuth` unused. |
| `uuid.uuid3` | no | Unused (we use `uuid5` — SHA-1, approved; L7). |

**Consequence — state this to an assessor rather than let them find it:** we **cannot** claim the
default provider is never loaded. Django loads it on every boot to name database indexes. The use is
non-security and correctly flagged `usedforsecurity=False`, which is what FIPS permits.

### 5.2 django-allauth + the OIDC provider (the default IdP path)

Audited because `allauth`'s OIDC provider is the intended default identity path.

- **allauth's own MD5** appears only in `mailru`, `odnoklassniki`, `draugiem` — legacy social
  providers, **not on the OIDC path**. Bare `md5()`; they would raise under FIPS if ever enabled.
- **allauth's SHA-1** is `mfa/totp` and `mfa/recovery_codes` (**HMAC-SHA1**, FIPS-approved) and
  `oauth2/utils.py` PKCE (**SHA-256**). All fine.
- **`id_token` verification is FIPS crypto.** Path:
  `openid_connect/views.py` → `socialaccount/internal/jwtkit.py::verify_and_decode` → **PyJWT** →
  `cryptography` (built `--no-binary`, D7) → system OpenSSL → **FIPS provider.**

Measured behaviour of each JWS algorithm under FIPS:

| Algorithm | Result | Note |
| --- | --- | --- |
| RS256 / PS256 (RSA ≥ 2048) | works | |
| ES256 / ES384 | works | the normal case |
| HS256 | works | HMAC-SHA256 |
| **EdDSA** (Ed25519) | **works** | in-module; FIPS 186-5 approves EdDSA (see L16) |
| **ES256K** (secp256k1) | **fails** | `InternalError: Unknown OpenSSL error` |
| **RSA-1024** | **fails** | `ValueError: Unable to sign/verify with this key` |

Two properties worth knowing:

1. **allauth trusts the algorithm the token claims.** `jwtkit.fetch_key` reads `alg` from the
   **unverified** header and passes `algorithms=[alg]` to `jwt.decode`. PyJWT's default set is
   `ES256, ES256K, ES384, ES512, ES521, EdDSA, HS256/384/512, PS256/384/512, RS256/384/512, none`.
   This is **not exploitable** — PyJWT refuses `alg=none` unless the key is `""`, and refuses an
   asymmetric key as an HMAC secret — but the accepted surface is wider than FIPS allows.
2. **In a federal deployment the IdP is itself FIPS-configured**, so only FIPS-compatible algorithms
   should ever arrive. The risk is a **non-FedRAMP IdP in a FedRAMP staging environment** — a real
   scenario we must support. There, verification fails **fail-closed but unhelpfully** (§5.3).

### 5.3 Failure modes under FIPS — debugging guide

**Read this first if a crypto operation fails only when `TAP_FIPS=1`.**

| Symptom (exact string) | Raised by | Meaning |
| --- | --- | --- |
| `ValueError: [digital envelope routines] unsupported` | `_hashlib`, `hashlib.md5()` | A **non-approved digest** (MD5) was requested for security use. The caller should pass `usedforsecurity=False` if the use is genuinely non-security. |
| `cryptography.exceptions.InternalError: Unknown OpenSSL error` | `cryptography`, key construction or verify | Almost always a **non-approved curve** — e.g. `secp256k1` (JWS `ES256K`). The message is generic; check the curve/algorithm. |
| `ValueError: Unable to sign/verify with this key` | `cryptography` RSA | **Key too small.** FIPS requires RSA ≥ 2048. |
| `UnsupportedAlgorithm` | `cryptography` | Algorithm absent from the active providers. |
| `openssl` CLI: `evp_generic_fetch: unsupported` | OpenSSL | Same as the first row, from the CLI. |

#### The trap: these do **not** reach allauth's error handling

Under FIPS, an OIDC login against an IdP using a non-approved algorithm fails **before** `jwt.decode`,
inside `jwtkit.fetch_key → algorithm.from_jwk()`. The exception is
`cryptography.exceptions.InternalError` or a plain `ValueError`. Neither is a `jwt.PyJWTError`
(so `jwtkit`'s `except jwt.PyJWTError` does not wrap it into an `OAuth2Error`), and neither is in
allauth's callback handler:

```python
# allauth/socialaccount/providers/oauth2/views.py  (OAuth2CallbackView.dispatch)
except (PermissionDenied, OAuth2Error, RequestException, ProviderException) as e:
    return render_authentication_error(request, provider, exception=e, ...)
```

**Result: the exception escapes both `try` blocks and becomes an uncaught HTTP 500.** No branded error
page, no `on_authentication_error` adapter hook, just a traceback. An operator federating a
non-FIPS IdP into a FedRAMP staging environment sees `Unknown OpenSSL error` and no explanation.

#### Where to fix it (designed, deliberately NOT built)

TAP already has the exact seam and an exact precedent:
`tap_auth/middleware.py::CallerContextMiddleware.process_exception` rescues a
`requests.RequestException` on an `/auth/` path into a branded 503
(`tap_web/auth/provider_unreachable.html`) rather than a raw 500. The FIPS case is the same shape:

1. Add a **generic, Django-free explainer** in `tap/` — e.g. `tap/crypto_errors.py::explain_crypto_error(exc) -> str | None`
   — that walks `exc.__cause__` / `__context__` and matches the signatures in the table above.
   It belongs in `tap/`, not `tap_auth/`, per the "no `tap_*` interdependencies; push shared
   mechanics down" rule in `CLAUDE.md`.
2. Add a branch to `process_exception`: on an `/auth/` path, if `explain_crypto_error(exception)`
   returns text, log it and render a new `tap_web/auth/provider_algorithm_unsupported.html`.
   Use **502** (the upstream IdP returned something we cannot process) rather than 503 — it is not
   transient, so no `Retry-After`.
3. Message should name the likely cause: *"the identity provider signed its `id_token` with an
   algorithm this FIPS-mode deployment cannot verify (e.g. `ES256K`, or an RSA key below 2048 bits).
   Configure the IdP to sign with RS256/PS256/ES256, or run this instance with `TAP_FIPS=0`."*
4. Optionally, pin an explicit JWS algorithm allowlist rather than accepting the token's claimed
   `alg`, which converts the opaque crypto error into a clean, early rejection.

Not built because FIPS is not yet live (`-6` unimplemented), so the code path is unreachable today.
**Build it in the same change that turns `TAP_FIPS=1` on**, and give it a spec RID alongside
`req-tap-auth-google-oidc`'s existing callback-hardening requirement.

### 5.4 The Postgres container — spiked, and it carries a NON-crypto hazard

The spec previously asserted *"Postgres = identical recipe on `wolfi-base` + `apk postgresql-16`."*
That was an assertion with no evidence. It has now been spiked (`spikes/fips/Dockerfile.postgres`,
`BUILD_EXIT=0`). **The crypto claim holds. A separate, larger hazard was found.**

**Crypto surface — all measured, under the FIPS provider:**

| Check | Result |
| --- | --- |
| `fipsinstall` on the PG image | self-tests pass; `fips 3.0.9` + `base` active |
| Postgres links **system** `libssl.so.3` / `libcrypto.so.3` | yes — the recipe transplants unchanged |
| `initdb` + server start under FIPS | **OK** |
| `password_encryption` | **`scram-sha-256`** (HMAC-SHA256 + PBKDF2, approved). A cluster using **`md5` auth would hard-fail** — check this before any FIPS cutover. |
| SCRAM password login | **authenticates** |
| `gen_random_uuid()` (OpenSSL DRBG) | **OK** |
| `sha256()` builtin | **OK** |
| **`SELECT md5('x')`** | **REFUSED** — `ERROR: could not compute MD5 hash: unsupported` |
| TLS ciphers offered | `TLS_AES_256_GCM_SHA384`, `TLS_AES_128_GCM_SHA256` only |

`SELECT md5()` is a **server-side builtin** routed through OpenSSL — a crypto surface the Django-side
audit (§5) cannot see. TAP never calls it: no `pgcrypto`, no `uuid-ossp`, only `plpgsql`. **Re-check
this whenever a plugin adds SQL**, since a single `md5()` in a query becomes a runtime error under FIPS.

**Wolfi ships `postgresql-16-oci-entrypoint`**, providing `/usr/bin/docker-entrypoint.sh` that honours
the same `POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST_AUTH_METHOD /
POSTGRES_INITDB_ARGS / POSTGRES_INITDB_WALDIR` contract and `docker-entrypoint-initdb.d` as the
official image. And `postgresql-16` is **16.14** — the exact version we run. So the DB image is a
**drop-in, not a reimplementation** of the official image's 389-line entrypoint.

#### ⚠️ The hazard: collation, not crypto

The outgoing `postgres:16-alpine` is **musl**; Wolfi is **glibc**. musl implements no locale collation,
so the outgoing cluster is **labelled `en_US.utf8` but sorts like `C`**. Measured:

| Cluster | `datcollate` | `ORDER BY` of `a, B, _b, A, b` |
| --- | --- | --- |
| `postgres:16-alpine` (musl) — **today** | `en_US.utf8` | `A  B  _b  a  b` |
| Wolfi (glibc) `--locale=C` | `C` | `A  B  _b  a  b`  ← **matches today** |
| Wolfi (glibc) `--locale=en_US.utf8` | `en_US.utf8` | `a  A  _b  b  B`  ← **different!** |

**Carrying the locale *label* across would silently change text sort order and text-index ordering.**
The correct move is `initdb --encoding=UTF8 --locale=C`, which reproduces the outgoing cluster's *actual*
behaviour and is additionally immune to the classic "a glibc upgrade invalidates your text indexes"
hazard. The `--locale=C` part was locked in as PROOF 3 of the spike (which fails the build on ordering
drift).

**⚠️ `--encoding=UTF8` is REQUIRED, and the spike missed it (productionization, 2026-07-21).** PROOF 3
only ran `ORDER BY` over ASCII letters — it never stored a UTF-8 value into a `varchar`. But
`initdb --locale=C` with **no explicit `--encoding` silently defaults to `SQL_ASCII`** (the C locale
implies no codeset), and under `SQL_ASCII` `varchar(n)` counts **bytes, not characters**, so any
multibyte UTF-8 value overflows. The outgoing `postgres:16-alpine` cluster was **UTF8**. Symptom when
the web image cut over first: ~half the test suite errored with
`DataError: value too long for type character varying(255)` on UTF-8 fixtures, while migrate (ASCII-only
at that point) passed — masking it. Fix: pin `--encoding=UTF8` explicitly *with* `--locale=C`, giving
UTF8 storage (matches the outgoing cluster) and C collation (matches musl's sort). Verified:
`server_encoding=UTF8`, `datcollate=C`, sort `A B _b a b`, full lane green. **Generalized lesson:** when
you change a locale to fix *collation*, you have also changed the *default encoding* — pin the encoding
explicitly, and test with real multibyte data, not just an ASCII `ORDER BY`.

Two consequences for the cutover:

- **The data volume must be recreated, not reused.** `datcollate` is recorded in the cluster; Postgres 15+
  will warn on a collation-version mismatch and text indexes built under the old collation may be subtly
  wrong. Dev does `dc down -v`; the promote gate provisions fresh databases. Any real deployment needs a
  dump/restore, not an in-place image swap.
- `--locale=C` means `ORDER BY <text>` is byte order (uppercase before lowercase). That is exactly what we
  get today, so **no query results change** — but it is now a *deliberate* choice rather than an accident
  of musl.

## 6. Verification suite (re-runnable ground truth)

**Run this before trusting any measurement in this document.** Base images move.

```sh
# Full recipe, three stages. Every assertion prints EXPECTED: when green; the build fails otherwise.
docker build -f spikes/fips/Dockerfile.fips --target ossl-builder   -t tap-fips:builder .
docker build -f spikes/fips/Dockerfile.fips --target fips-runtime   -t tap-fips:runtime .
docker build -f spikes/fips/Dockerfile.fips --target crypto-runtime -t tap-fips:crypto  .

# The distroless / package-manager disproof (context for the base-image decision).
docker build -f spikes/distroless/Dockerfile.distroless --target proof -t tap-distroless:proof .
docker build -f spikes/distroless/Dockerfile.ubi-micro  --target proof -t tap-ubi:proof .
```

### The assertions that must hold

Each is stated as a **falsifiable check with a negative control**. A FIPS claim backed only by
"the approved thing worked" is worthless; you must also show the non-approved thing was *refused*.

| ID | Check | Expected |
| --- | --- | --- |
| `F1` | `openssl list -providers` | contains `fips` **active**, version `3.0.9`; `default` **absent** |
| `F2` | `openssl fipsinstall … -module fips.so` | self-tests pass, MAC written (proves binary-compat) |
| `F3` | `echo x \| openssl dgst -sha256` | succeeds (approved) |
| `F4` | `echo x \| openssl dgst -md5` | **fails** — `evp_generic_fetch: unsupported` (negative control) |
| `F5` | `python -c "import ssl; print(ssl.OPENSSL_VERSION)"` | matches the **system** OpenSSL (proves dynamic linkage, no rebuild) |
| `F6` | `_hashlib.new("md5", b"x")` | raises `ValueError` (negative control, no builtin fallback) |
| `F7` | `type(hashlib.sha256()).__module__` | `"_hashlib"` (proves OpenSSL-backed, not a builtin) |
| `F8` | `hashlib.sha1(b"x")` | succeeds (SHA-1 is approved — L6) |
| `F9` | `uuid.uuid5(uuid.NAMESPACE_DNS, "x")` | succeeds (L7 — the boot-critical one) |
| `F10` | `cryptography` `backend.openssl_version_text()` | matches **system** OpenSSL (proves `--no-binary` worked, not the bundled wheel) |
| `F11` | `ec.generate_private_key(ec.SECP256R1())` + sign + verify | succeeds (the passkey path, through FIPS) |
| `F12` | `hashes.Hash(hashes.MD5())` via `cryptography` | raises `InternalError` (negative control) |
| `F13` | grep the installed dep closure for `hashlib.md5(` without `usedforsecurity=False` | only `MD5PasswordHasher` (unreachable) + `faker` (test-only) |
| `F14` | `OPENSSL_CONF=/dev/null openssl list -providers` | shows **`default` active** — proving the boundary is the config, not the modules dir (L13). Do **not** cite `ls ossl-modules/` as evidence. |
| `F15` | `openssl req -new -newkey ec:… -subj /CN=x` | succeeds, `ecdsa-with-SHA256` — the `.include ca.cnf` trap is closed (L14) |
| `F16` | Postgres: `SELECT md5('x')` under FIPS | **refused** — `could not compute MD5 hash: unsupported` (negative control, server-side) |
| `F17` | Postgres: `SHOW password_encryption` | `scram-sha-256` — `md5` auth would hard-fail under FIPS |
| `F18` | Postgres: `initdb --locale=C` sort of `a,B,_b,A,b` | `A B _b a b` — collation parity with the outgoing musl cluster (§5.4) |
| `F19` | Web: `psycopg.connect(...)` to the DB under FIPS | **succeeds** with `psycopg[c]` (system libpq); the negative control is `psycopg[binary]`, which fails `could not generate nonce` — proving the bundled-OpenSSL trap (L17) and its fix |

Machine-readable form for an automated assessor:

```json
{
  "assessment": "tap-fips-openssl-4282",
  "recorded": "2026-07-09",
  "provider_set": ["fips", "base"],
  "module": {"cert": "CMVP #4282", "version": "3.0.9", "self_built": true},
  "host_libcrypto": {"measured": "3.6.3", "binary_compat_verified": true},
  "checks": [
    {"id": "F1",  "kind": "positive", "target": "openssl-cli",   "assert": "fips provider active"},
    {"id": "F4",  "kind": "negative", "target": "openssl-cli",   "assert": "md5 refused"},
    {"id": "F6",  "kind": "negative", "target": "python-_hashlib","assert": "md5 raises ValueError"},
    {"id": "F7",  "kind": "positive", "target": "python-hashlib", "assert": "sha256 backed by _hashlib"},
    {"id": "F9",  "kind": "positive", "target": "python-uuid",    "assert": "uuid5 works (SHA-1 approved)"},
    {"id": "F10", "kind": "positive", "target": "cryptography",   "assert": "links system OpenSSL"},
    {"id": "F11", "kind": "positive", "target": "cryptography",   "assert": "P-256 ECDSA sign+verify"},
    {"id": "F12", "kind": "negative", "target": "cryptography",   "assert": "MD5 raises InternalError"}
  ],
  "invariant": "every positive check MUST be paired with a negative control; a passing positive check alone does not evidence enforcement"
}
```

## 7. Open risks — do NOT report these as closed

### 7.1 Operational Environment (OE) vendor-affirmed portability — **ACCEPTED RISK, OWNED**

**Status: accepted, 2026-07-09. Owner: George.** Non-technical. Does **not** block productionization.

#4282's security policy lists the platforms on which the module was **tested**. Wolfi is not among
them. We therefore rely on **FIPS 140-3 vendor-affirmed portability** (same CPU architecture, same
libc; the vendor — us — affirms correct operation). This is common and widely accepted, but a
3PAO / compliance authority has final say.

**The risk is owned deliberately, on domain expertise** (the owner contributed to getting FIPS +
STIG sorted for the Wolfi/Chainguard line originally), and it is **cheap to be wrong about**, because
the fallback is a **base-image swap, not a rewrite.** That is the payoff of having stayed in the
Wolfi family: the escalation ladder never leaves the architecture.

**Escalation ladder, cheapest first — if a 3PAO rejects vendor-affirmed OE:**

1. **Swap to Chainguard's validated FIPS image** (same Wolfi family, glibc, same `apk` binaries).
   Their CMVP-validated module replaces our self-built `fips.so`; the `fipsinstall` + `openssl.cnf`
   steps (§3 steps 1–3) largely fall away. **Everything else in this document still holds** — in
   particular `--no-binary cryptography` (D7/L9) and the fail-closed boot assertion (D15) remain
   mandatory. Cost: a commercial licence (possibly discounted). **Switching cost: near-zero.**
2. **Evaluate DHI's free `3.14-fips` variant** (`dhi.io`, Apache-2.0, $0). **UNVERIFIED** — we could
   not pull it (HTTP 401, login required) and never confirmed its Python version, FIPS activation
   model (in-image vs host-derived, §4/L10), or `-dev` build story. Verify before relying on it.
   Its authenticated pull also conflicts with `req-cicd-base-image-sourcing`'s anonymous-pull property.
3. **UBI + host-derived FIPS** — the already-proven `ubi-micro` + `dnf --installroot` path
   (`spikes/distroless/Dockerfile.ubi-micro`). RHEL 9 *is* a CMVP-**tested** OE, so this resolves the
   OE question outright — at the cost that the **deployment host must run `fips=1`**, which we cannot
   guarantee on customer-controlled infrastructure (§4/L10). Last resort, not first.

**Why this is no longer the blocking question:** every rung of the ladder terminates in a working,
already-demonstrated build. Proceed with the self-built #4282 provider (D2) as the default.

### 7.2 `usedforsecurity=False` is a reachable non-validated path

Documented in L8. Permitted by FIPS for non-security use. Must be **named** in the risk register,
not implied absent. An assessor will ask.

### 7.3 `_blake2` remains a built-in, non-validated implementation

Wolfi's CPython omits `_md5`/`_sha1`/`_sha2`/`_sha3` but **ships `_blake2`**. An in-process
non-validated hash implementation is therefore importable. Not used by TAP; disclose it.

### 7.4 Dependency drift is a boot-breaking regression class

Under `TAP_FIPS=1`, a **new bare `hashlib.md5()` in a runtime dependency crashes boot.** This is
exactly what the fail-closed boot check (D15) is designed to catch, but it should be caught earlier:
**re-run check `F13` on every Renovate auto-patch PR** (`req-cicd-base-image-lifecycle-1`).

### 7.5 `fipsinstall` reproducibility

The MAC pins the exact `fips.so` bytes. It must run **in the final image**, and must re-run if the
module is rebuilt. Fits the build-stage model; noted so nobody "optimizes" it into a cached layer.

### 7.6 Productionization status

**Web image: DONE (2026-07-21).** The recipe is folded into the real `Dockerfile` and validated:

- ✅ Wolfi base + FIPS builder stage in the real `Dockerfile`; `ARG TAP_FIPS` (default 1) selects
  the variant; `docker-compose.yml` wires the build arg (`TAP_FIPS=0` escape hatch).
- ✅ `[tool.uv] no-binary-package = ["cryptography"]`; `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1`.
- ✅ `org.tap.fips` label + `TAP_FIPS_MODE` env (D12–D14).
- ✅ Fail-closed boot self-check (`tap.fips`, D15) wired in `docker/entrypoint.sh` + its **Validation
  Map row** (`req-cicd-base-image-lifecycle-6`) + unit tests.
- ✅ Full boot + `scripts/test --gryphon` lane green under `TAP_FIPS=1` (2285 passed); F1–F13/F19 re-run.
- ✅ **`psycopg[binary]` → `psycopg[c]`** (L17 — the one hard-fail found; bundled-OpenSSL SCRAM break).
- ✅ OIDC crypto-error rescue built (`tap.crypto_errors` + middleware 502, §5.3;
  `req-tap-auth-google-oidc-fips-algorithm`).

**Postgres image: DONE (2026-07-21).** `docker/postgres/Dockerfile` — minimal `wolfi-base` +
`postgresql-16` (16.14) + `postgresql-16-oci-entrypoint` (the canonical docker-library entrypoint) +
`gosu` + the same FIPS builder/config recipe (D10). `docker-compose.yml` builds it with the `TAP_FIPS`
arg. Validated: `fipsinstall` self-tests pass; `server_encoding=UTF8`, `datcollate=C` (initdb
`--encoding=UTF8 --locale=C` — UTF8 is **required**, see §5.4); sort parity `A B _b a b`; `SELECT md5()`
refused; `password_encryption=scram-sha-256`; `gen_random_uuid()`/`sha256()` OK; the web container
connects via `psycopg[c]` under **double-FIPS** SCRAM; full lane green. The data volume was recreated
(`dc down -v`) because `datcollate` is baked at initdb.

Still outstanding:

- **CI gating of both variants** (D13) — build + gate `TAP_FIPS=1` and `=0` (web + DB) so the escape
  hatch cannot rot.

## 8. The assessment methodology (reusable)

How the above was established, stated generally so it can be re-applied.

1. **Separate the two bars first** (§1). "We need FIPS" is ambiguous and the answer changes the
   architecture. Ask which one.
2. **Find the load-bearing claim and test *it*, not its neighbours.** Here it was: *can a frozen,
   validated 3.0.9 `fips.so` load into a modern libcrypto?* Everything else was downstream of that
   one yes/no. It was tested in the first build.
3. **Every positive check needs a negative control.** "sha256 works" evidences nothing about
   enforcement. "md5 is *refused*" does. A FIPS assessment without negative controls is theatre.
4. **Probe the lowest layer that cannot fall back.** `hashlib` façades over `_hashlib`; `_hashlib`
   cannot fall back. Test at the layer where a silent alternative implementation does not exist (L5).
5. **Distinguish "parsed" from "took effect."** Ask the system to *report its state*
   (`openssl list -providers`), don't infer state from the absence of an error (L1).
6. **Suppressing errors on a discovery step converts failure into a silent wrong answer.**
   `2>/dev/null || true` around anything whose output you subsequently trust is a bug (L2).
7. **Measure; don't cite.** Every ecosystem claim in L11 was confidently asserted and false. Pull the
   image, run the binary, read the version. A research pass proposes; a `docker run` disposes.
8. **Enumerate primitives reached, not call sites named.** Grepping `hashlib` misses `uuid5` (L7).
   Ask "what crypto executes," then find who calls it.
9. **Audit the dependency closure, not just first-party code.** The one real MD5 risk lived in
   Django and `faker`, not in TAP.
10. **Verify the harness itself.** Confirm you're reading the exit code of the thing under test (L12).
11. **Record what is *not* proven.** §7 exists so the next assessor doesn't inherit false confidence.

## 9. Provenance

All measurements 2026-07-09, arm64 (Apple Silicon), on:
`cgr.dev/chainguard/wolfi-base` (system OpenSSL **3.6.3**, CPython **3.14.6**),
self-built OpenSSL **3.0.9** FIPS provider (**CMVP #4282**), `cryptography` **49.0.0** built
`--no-binary`. Comparators: `cgr.dev/chainguard/python:latest{,-dev}`,
`registry.access.redhat.com/ubi9/{ubi,ubi-minimal,ubi-micro,python-312}`, `ubi10/ubi-minimal`,
`gcr.io/distroless/python3-debian13`, `dhi.io/python` (401, unverified).

Evidence: `spikes/fips/`, `spikes/distroless/`.
Commits: `1fbadf11` (FIPS spike), `53e7b15a` (distroless disproof), `08ec2905` (spec + FIPS default-on).

## References

- [OpenSSL `fips_module(7)`](https://docs.openssl.org/3.3/man7/fips_module/) — the binary-compatibility guarantee (D4)
- [OpenSSL README-FIPS](https://github.com/openssl/openssl/blob/master/README-FIPS.md)
- [CMVP #4282](https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/4282)
- [OpenSSL 3.0.9 FIPS validated](https://www.openssl.org/blog/blog/2024/01/23/fips-309/)
- [pyca/cryptography installation (system OpenSSL)](https://cryptography.io/en/latest/installation/)
- [pyca/cryptography bundled-OpenSSL FIPS issue #5008](https://github.com/pyca/cryptography/issues/5008)
- [Red Hat: adding software to a UBI container (`dnf --installroot`)](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/building_running_and_managing_containers/assembly_adding-software-to-a-ubi-container_building-running-and-managing-containers)
- Companion doc: [doc-hardened-base-image-landscape](doc-hardened-base-image-landscape.md)
