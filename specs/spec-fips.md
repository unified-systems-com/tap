# FIPS Cryptographic Posture

## Overview

This spec is the **center of gravity for FIPS** — the single authoritative place that describes
everything TAP does around FIPS 140-3 and cryptographic-provider provenance. It **owns** the
cross-cutting requirements (the crypto Bill-of-Materials and its gates) and provides an authoritative
**FIPS Requirement Map** that indexes every FIPS requirement in the codebase, including the ones that
keep their structural home in another spec (the base-image build recipe, the OIDC crypto-error rescue,
the plugin manifest declaration). It follows the same "center of gravity + Map" pattern as
[spec-security-posture.md](spec-security-posture.md) and [spec-dev-validation.md](spec-dev-validation.md):
it references leaf surfaces rather than absorbing them, so there is one place to read the whole FIPS
story without duplicating the requirements that naturally live with their subsystem.

The exhaustive decision record — decisions D1–D17 with reversal triggers, lessons L1–L17 (several are
fail-*open* traps), TAP's audited crypto surface, and a re-runnable verification suite F1–F19 where
every positive check is paired with a negative control — is
[doc-fips-assessment-record.md](../docs/misc/doc-fips-assessment-record.md). That doc is the detailed,
measurement-backed artifact; **this spec is the authoritative behavioral contract and the index.**
When they disagree, re-run the verification suite: base images move.

## The two bars (say which one you mean)

"We need FIPS" is ambiguous and the answer changes the architecture. Two very different bars hide under
the word, and every FIPS conversation should name which one:

| Bar | Meaning | TAP's position |
| --- | --- | --- |
| **Use FIPS-validated crypto** | A technical control: crypto operations execute inside a NIST CMVP-validated module, in FIPS mode, approved-algorithms-only. | **Built.** The self-built OpenSSL 3.0.9 FIPS provider (CMVP #4282), on both containers, default-on. |
| **Be a FIPS-certified platform** | An audit posture (FedRAMP/DoD): the module's certificate covers *your* Operational Environment and a 3PAO signs off. | **Positioned for.** Rests on the OE vendor-affirmation question — an accepted, owned risk with a base-image-swap fallback ladder (doc §7.1). |

## The invariant

> **Every cryptographic *provider* that can execute inside the deployed artifact is the validated
> module (the system OpenSSL #4282 provider), or that ecosystem's validated equivalent — or is proven
> unreached, or explicitly named out-of-boundary.**

OpenSSL is merely the provider TAP's *Python* uses. A Go binary, a Rust crate on `ring`/`aws-lc-rs`, a
`libsodium`/`pynacl` wheel, or a JVM's BouncyCastle each carries its OWN crypto that is invisible to
`OPENSSL_CONF` and would silently run non-FIPS crypto with no error. The FIPS posture is therefore not
"grep for MD5" — it is an accounting of every crypto provider present, which is what the crypto Bill-of-
Materials (`req-fips-crypto-bom`) enforces.

## Declare vs. decide (the plugin authority model)

Not every plugin need be FIPS-compatible — a non-FIPS deployment may legitimately use non-FIPS crypto.
But a FIPS-mode system must not silently leak. The authority model that makes this robust separates two
roles, and is the reason a plugin can never exempt itself:

- **The plugin author DECLARES** posture (factual) in the manifest `[fips]` table — VERIFIED against
  the scan, never trusted (`req-tap-plugin-manifest-v0-fips`).
- **The system ENFORCES globally**: in FIPS mode, every assembled plugin must be validated
  (`req-fips-crypto-bom-system-gate`).
- **The operator DECIDES exceptions**: only the deployer waives, per-plugin, in the boot profile, with
  a **mandatory reason**, surfaced and auditable (`req-fips-crypto-bom-waivers`). A plugin cannot excuse
  itself from a deployment's FIPS posture — that would be the leak the whole system closes.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-fips-crypto-bom | [Crypto Bill-of-Materials](#crypto-bill-of-materials) | Implemented | Enumerate every crypto provider in an artifact (not just OpenSSL); classify each against a curated registry; fail-closed on the unaccounted. `tap.crypto_bom` + `tap.crypto_providers`. |
| req-fips-crypto-bom-ci | [Per-Commit CI Gate](#per-commit-ci-gate) | Implemented | The gate over the installed union (`test_all`), per-commit. `tap/tests/test_crypto_bom.py`. |
| req-fips-crypto-bom-conformance | [Per-Plugin Conformance](#per-plugin-conformance) | Implemented | Authoring-time report of a plugin's crypto posture + declaration verification. `validate_plugin` `crypto-providers` check. |
| req-fips-crypto-bom-system-gate | [Boot-Time System Gate](#boot-time-system-gate) | Implemented | Global validation at boot under `TAP_FIPS_MODE=1`: core + every plugin, TAP-ABORT on an unwaived non-validated provider. `python -m tap.crypto_bom --gate`. |
| req-fips-crypto-bom-waivers | [Operator Waivers](#operator-waivers) | Implemented | The justified escape valve: boot-profile `fips_waivers`, deployment-controlled, mandatory reason, surfaced. |
| req-fips-crypto-bom-jvm | [JVM-Arrival Tripwire](#jvm-arrival-tripwire) | Implemented | Java is out of scope, but its arrival (runtime/executable/jar/bridge dist) fails the gate loudly — jars are not ELF, so nothing else catches it. |
| req-fips-crypto-bom-source | [Source-Level Scan](#source-level-scan) | Implemented | The Python analog of the ELF fingerprinter: AST-scan TAP + plugin source for pure-Python crypto imports, bare weak-digest usage, and WASM-runtime imports — the crypto the native scan cannot see. |

### Crypto Bill-of-Materials
----
RID: `req-fips-crypto-bom`
Status: `Implemented`

`tap.crypto_bom` fingerprints every ELF artifact in a scanned environment for crypto-provider byte
signatures (Go via the build-info magic, Rust `ring`/`aws-lc-rs`, `libsodium`, mbedTLS/wolfSSL/GnuTLS/
NSS/BoringSSL, and a bundled OpenSSL — separate-file or the count check) and classifies each against
the curated registry in `tap.crypto_providers`. Each detected provider resolves to a **disposition**:
`VALIDATED` (routes through the system OpenSSL #4282, directly or via the system libpq/libcurl),
`OUT_OF_BOUNDARY` (provisioning/supply-chain crypto, e.g. `uv`'s aws-lc-rs at install time, named-
accepted), `UNREACHED` (present but never executes a security operation, e.g. `gosu`'s dormant Go
crypto/tls), or `MUST_FIX`. A provider with **no disposition** is unclassified and **fails the gate
(fail-closed)** — a new dependency or binary carrying an unknown crypto provider cannot ship until a
human classifies it. Adding a disposition is the reviewable decision (the same discipline as
`tap.guards.surfaces.DECLARED_SURFACES`).

Robustness invariants: Go is disambiguated from a stray `crypto/tls` string by requiring the Go
build-info magic; real paths are resolved so the Wolfi `/bin`→`/usr/bin` and `/lib`→`/usr/lib` symlinks
do not double-count (doc L4); the OpenSSL-version-banner heuristic is deliberately NOT a signal (it is
build metadata, e.g. `git` embeds the system banner); and an anti-fail-open sentinel asserts the scan
actually read binaries and saw the known providers (doc L2/L12).

#### Acceptance Criteria

| RID | Name | Status | Detail | Notes |
| --- | --- | :---: | --- | --- |
| req-fips-crypto-bom-1 | Provider enumeration | Implemented | Fingerprints native artifacts for non-OpenSSL provider signatures + the bundled-OpenSSL classes; `openssl-system` (incl. via libpq/libcurl) is VALIDATED. | |
| req-fips-crypto-bom-2 | Curated dispositions, fail-closed | Implemented | Every detected provider needs a disposition (VALIDATED/out-of-boundary/unreached/must-fix); an undispositioned one fails. | The reviewable decision; `tap.crypto_providers`. |
| req-fips-crypto-bom-3 | Reusable scope | Implemented | `scan()` takes explicit roots — the same call scans core's environment or a single plugin's isolated closure. | Enables the per-plugin conformance surface. |

### Per-Commit CI Gate
----
RID: `req-fips-crypto-bom-ci`
Status: `Implemented`

`tap/tests/test_crypto_bom.py` runs `core_report()` over the installed environment and asserts no
unclassified or non-validated provider. Under the `test_all` profile the venv is the full plugin union,
so this catches a plugin that leaks a non-FIPS provider in core CI — making core FIPS-capable is
worthless if a plugin ships `pynacl` or a Go collector. The gate also asserts it actually read binaries
and saw the known providers, so an empty scan fails loudly instead of a false all-clear.

### Per-Plugin Conformance
----
RID: `req-fips-crypto-bom-conformance`
Status: `Implemented`

The `validate_plugin` `crypto-providers` check (`tap.crypto_bom.scan_plugin`) scans a plugin's shipped
native artifacts + declared dependencies and reports its crypto posture, and VERIFIES the manifest
`[fips]` declaration (`req-tap-plugin-manifest-v0-fips`) against the scan: a false `compatible` FAILS, an
honest `uses-nonvalidated` PASSES, an undeclared leak WARNs. A warning by default (a plugin may
legitimately use non-FIPS crypto in a non-FIPS deployment); `--strict` conformance CI escalates it.

### Boot-Time System Gate
----
RID: `req-fips-crypto-bom-system-gate`
Status: `Implemented`

`python -m tap.crypto_bom --gate`, wired into `docker/entrypoint.sh` after the `tap.fips` self-check.
When `TAP_FIPS_MODE=1` it scans the whole assembled environment — core + every installed plugin — and
emits `TAP-ABORT`, refusing to serve, if any crypto provider is non-validated, unless an operator waiver
excuses it. No-op when FIPS is off (a non-FIPS deployment may use non-FIPS crypto). This is the "global
validation" half of declare-vs-decide: `tap.fips` proves the OpenSSL-backed Python layer is enforced,
but it is blind to a plugin's own non-OpenSSL crypto — this gate is what sees it.

### Operator Waivers
----
RID: `req-fips-crypto-bom-waivers`
Status: `Implemented`

The deployment-side escape valve. The boot profile's `fips_waivers` array (schema in
`tap_boot/schemas/boot.schema.json`) names, per entry, a plugin/artifact + provider being excused and a
**mandatory `reason`** — a blank reason is rejected (you cannot waive silently). A waived finding stops
being a failure but is **recorded as WAIVED with its reason**, so every FIPS exception is auditable
rather than hidden. Waivers live in the boot profile (operator-controlled), never in the plugin's own
manifest: authority to waive a system security property rests with the deployer, not the code author.

### JVM-Arrival Tripwire
----
RID: `req-fips-crypto-bom-jvm`
Status: `Implemented`

Java/BouncyCastle is out of the current scope (Python + subprocess Go tools + Rust extensions), but its
arrival must not be silent: jars/classes/`libjvm.so` are not ELF, so the fingerprinter is blind to JVM
crypto (JCA providers / BouncyCastle → BC-FIPS). The gate fails-closed the moment a JVM runtime,
executable, `.jar`/`.class` artifact, or bridge distribution (`jpype`/`pyjnius`/`jep`/`py4j`) appears —
the loud "now build the Java crypto layer" signal, rather than shipping a silent non-FIPS JVM.

### Source-Level Scan
----
RID: `req-fips-crypto-bom-source`
Status: `Implemented`

The ELF fingerprinter sees *native* crypto and the dist-name check sees *known installed packages*.
Neither sees crypto that is **pure-Python** (no native extension to fingerprint) or a weak primitive
*used* in our own source. `tap.crypto_bom.scan_source` closes that gap — the Python analog of the ELF
signatures, run over TAP core + installed plugin source as part of `core_report` and `scan_plugin`:

1. **Non-validated crypto imports** — an AST walk flags `import ecdsa`/`rsa`/`nacl`/`Crypto`/`jose`/
   `passlib`/… (pure-Python or non-OpenSSL crypto). `hashlib`/`hmac`/`secrets`/`ssl`/`cryptography`/
   `psycopg` are *not* flagged — they route through the system OpenSSL. Undispositioned → fails.
2. **Bare weak-digest usage** — `hashlib.md5(…)` / `hashlib.new("md5", …)` / a bare `md5(…)` for a
   *security* use (no `usedforsecurity=False`) is a latent bomb (it raises under FIPS only when the
   path executes); flagged at build time — automating the assessment record's F13. SHA-1 is approved
   as a hash and is not flagged.
3. **WASM-runtime tripwire** — WebAssembly crypto cannot execute without a host runtime, and in Python
   that runtime is a package (`wasmtime`/`wasmer`/`pywasm`). Detecting the runtime (import or installed
   dist) is the tripwire, exactly like the JVM's `libjvm.so` — the opaque `.wasm` module itself is not
   parsed (it is frequently stripped; the runtime is the honest, cheap entry-point catch).

AST (not grep) so a string literal like `"md5"` in a data table is never mistaken for a call. Test code
and `tap.fips` itself are skipped — they legitimately execute MD5 as negative controls. The expanded
`KNOWN_NONFIPS_DISTRIBUTIONS` denylist (ecdsa, rsa, python-jose, passlib, …) catches the same pure-Python
crypto at the *installed-package* layer too, so a transitive pull is caught by name even when never
directly imported. **Residuals (named):** a *novel* crypto module name absent from the registry, and
crypto inside a third-party dependency's own source (not TAP/plugin source), remain the same
fail-open-on-the-unknown edge the ELF signatures have.

## FIPS Requirement Map

The authoritative inventory of every FIPS requirement in the codebase. Requirements **owned here** carry
the full contract above; requirements **homed elsewhere** keep their structural spec (the base-image
build recipe belongs with the base image; the OIDC rescue with auth; the manifest declaration with the
manifest) and are indexed here so the whole FIPS posture reads from one place. Adding a FIPS requirement
anywhere requires adding its row here in the same change.

| Requirement | Home spec | What it covers |
| --- | --- | --- |
| `req-fips-crypto-bom` (+ `-ci`, `-conformance`, `-system-gate`, `-waivers`, `-jvm`) | **this spec** | The crypto Bill-of-Materials: scanner, registry, CI gate, per-plugin conformance, boot-time global gate, operator waivers, JVM tripwire. |
| `req-cicd-base-image-lifecycle-3` | [spec-cicd-hardening.md](spec-cicd-hardening.md) | Wolfi is the standard base — chosen partly for in-image, host-independent FIPS (also for Python-currency + CVE floor). |
| `req-cicd-base-image-lifecycle-5` | [spec-cicd-hardening.md](spec-cicd-hardening.md) | The FIPS crypto recipe: self-built OpenSSL 3.0.9 #4282 on web + DB, `fipsinstall` in-image, `--no-binary cryptography`, `psycopg[c]` (system libpq), Postgres `--encoding=UTF8 --locale=C`. |
| `req-cicd-base-image-lifecycle-6` | [spec-cicd-hardening.md](spec-cicd-hardening.md) | The build flag (`ARG TAP_FIPS`, default 1) + machine-legible mode (`org.tap.fips` label, `TAP_FIPS_MODE`) + the fail-closed `tap.fips` boot self-check. |
| `req-tap-auth-google-oidc-fips-algorithm` | [spec-tap-auth-v0.md](../tap_auth/specs/spec-tap-auth-v0.md) | The OIDC crypto-error rescue: a FIPS/algorithm clash during login (`ES256K`, RSA<2048) renders a branded 502 instead of an uncaught 500. |
| `req-tap-plugin-manifest-v0-fips` | [spec-tap-plugin-manifest-v0.md](../tap_plugins/specs/spec-tap-plugin-manifest-v0.md) | The plugin author's `[fips]` declaration (`compatible` / `uses-nonvalidated` + reason) — the "declare" half of declare-vs-decide, verified by conformance. |

## Open risks

Owned in full by the assessment record (doc §7); named here so the posture stays honest:

- **OE vendor-affirmed portability** (doc §7.1) — accepted + owned; not a blocker. Fallback ladder is a
  base-image swap, not a rewrite.
- **`usedforsecurity=False`** reaches MD5 via a separate non-FIPS libctx (doc §7.2) — permitted, disclosed.
- **`_blake2`** is a built-in non-validated hash, importable though unused (doc §7.3).
- **Dependency drift** — a new bare `hashlib.md5()`/`SELECT md5()` in a dependency is a boot-breaking
  regression under FIPS; caught by the boot self-check + `F13`/`F16` (doc §7.4).
- **CI dual-gating** of both `TAP_FIPS` variants is still pending (doc §7.6).
- **Per-runtime runtime self-checks** — `tap.fips` is the Python/OpenSSL instance of a general pattern;
  an in-boundary Go binary needs `GODEBUG=fips140=on` + a self-test, a JVM needs BC-FIPS, Rust needs
  aws-lc-rs FIPS mode. Deferred until a non-Python runtime enters the boundary.
