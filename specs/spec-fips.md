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
| **Use FIPS-validated crypto** | A technical control: crypto operations execute inside a NIST CMVP-validated module, in FIPS mode, approved-algorithms-only. | **FIPS mode on, approved-algorithms-only, provider built from OpenSSL's FIPS code line at a patched version — NOT validated as shipped once the pin moves off a certified version (decision D17, 2026-09-02).** The self-built provider on both containers, default-on; whether the pinned version carries a certificate is DERIVED from `docker/build-openssl-fips.sh` (`tap.fips_pins`), stamped on the SBOM, and guard-checked — never asserted by hand (`req-fips-pin-currency-8`). |
| **Be a FIPS-certified platform** | An audit posture (FedRAMP/DoD): the module's certificate covers *your* Operational Environment and a 3PAO signs off. | **Deferred.** The re-pin path is named: for a build an audit needs the certificate for, pin a version in the `OSSL_CMVP_VALIDATED` table (3.0.9/#4282 or 3.1.2/#4985) via the `bump-openssl-fips` skill and the derived posture flips back to validated. The OE vendor-affirmation question (doc §7.1) then applies as before. |

## The invariant

> **Every cryptographic *provider* that can execute inside the deployed artifact is the system
> OpenSSL FIPS provider at the pinned version — CMVP-validated, or a recorded security-driven build
> of the FIPS code line (D17), and the crypto-BOM says which — or that ecosystem's validated
> equivalent, or is proven unreached, or explicitly named out-of-boundary.**

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
| req-fips-pin-currency | [Pin Currency](#pin-currency) | Partial | The validated module's pins are re-asserted against upstream, and a bump is transcribed rather than typed. `scripts/verify-openssl-release` built; the schedule is open. |

### Crypto Bill-of-Materials
----
RID: `req-fips-crypto-bom`
Status: `Implemented`

`tap.crypto_bom` fingerprints every ELF artifact in a scanned environment for crypto-provider byte
signatures (Go via the build-info magic, Rust `ring`/`aws-lc-rs`, `libsodium`, mbedTLS/wolfSSL/GnuTLS/
NSS/BoringSSL, and a bundled OpenSSL — separate-file or the count check) and classifies each against
the curated registry in `tap.crypto_providers`. Each detected provider resolves to a **disposition**:
`VALIDATED` (routes through the system OpenSSL provider at a CMVP-validated pinned version, directly
or via the system libpq/libcurl), `FIPS_MODE_UNVALIDATED_BUILD` (the same route while the pinned
version carries no certificate — FIPS mode on, approved-algorithms-only, a recorded security-driven
build per D17; a distinct state so presence can never read as a certificate, and not a failure),
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
| req-fips-crypto-bom-1 | Provider enumeration | Implemented | Fingerprints native artifacts for non-OpenSSL provider signatures + the bundled-OpenSSL classes; `openssl-system` (incl. via libpq/libcurl) takes the boundary DERIVED from the pin — VALIDATED or FIPS_MODE_UNVALIDATED_BUILD — and is unclassified (fails) when the pin is unreadable. | `tap.crypto_providers.system_openssl_boundary()` classifies against the RUNNING provider version (the active `fips` provider when observable, the pin otherwise) looked up in the CMVP table; `tap.crypto_bom.shipped_provider_finding` records a pin/active mismatch (code newer than its image, or the reverse) visibly without refusing — the running provider is the FIPS fact, and the lean-boot gate runs every branch against the published image by design. |
| req-fips-crypto-bom-2 | Curated dispositions, fail-closed | Implemented | Every detected provider needs a disposition (VALIDATED / FIPS_MODE_UNVALIDATED_BUILD / out-of-boundary / unreached / must-fix); an undispositioned one fails. | The reviewable decision; `tap.crypto_providers`. |
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

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-fips-crypto-bom-ci-1 | Core CI asserts a clean environment | Implemented | `tap/tests/test_crypto_bom.py` runs `core_report()` over the installed environment; an unclassified or non-validated provider fails. | |
| req-fips-crypto-bom-ci-2 | Empty scan fails loudly | Implemented | The CI assertion requires that binaries were actually read and the known providers were seen — an empty scan is a failure, never a false all-clear. | |
| req-fips-crypto-bom-ci-3 | Plugin-union coverage | Implemented | Under the `test_all` profile the venv is the full plugin union, so a plugin leaking a non-FIPS provider reds core CI. | |

### Per-Plugin Conformance
----
RID: `req-fips-crypto-bom-conformance`
Status: `Implemented`

The `validate_plugin` `crypto-providers` check (`tap.crypto_bom.scan_plugin`) scans a plugin's shipped
native artifacts + declared dependencies and reports its crypto posture, and VERIFIES the manifest
`[fips]` declaration (`req-tap-plugin-manifest-v0-fips`) against the scan: a false `compatible` FAILS, an
honest `uses-nonvalidated` PASSES, an undeclared leak WARNs. A warning by default (a plugin may
legitimately use non-FIPS crypto in a non-FIPS deployment); `--strict` conformance CI escalates it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-fips-crypto-bom-conformance-1 | Scan verifies the declaration | Implemented | `scan_plugin` checks shipped native artifacts + declared dependencies against the manifest `[fips]` declaration; a false `compatible` FAILS. | Declare-vs-decide, verified. |
| req-fips-crypto-bom-conformance-2 | Honest non-validated passes | Implemented | A plugin declaring `uses-nonvalidated` passes the check. | Honesty is not punished. |
| req-fips-crypto-bom-conformance-3 | Undeclared leak warns, strict escalates | Implemented | An undeclared provider WARNs by default; `--strict` promotes the warning to a failure. | |

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

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-fips-crypto-bom-system-gate-1 | Gate wired after the self-check | Implemented | `python -m tap.crypto_bom --gate` runs in `docker/entrypoint.sh` after the `tap.fips` self-check. | |
| req-fips-crypto-bom-system-gate-2 | FIPS-on refuses on non-validated | Implemented | With `TAP_FIPS_MODE=1`, any non-validated provider without an operator waiver emits `TAP-ABORT` and the instance refuses to serve. | |
| req-fips-crypto-bom-system-gate-3 | FIPS-off is a no-op | Implemented | With FIPS mode off the gate does nothing — a non-FIPS deployment may use non-FIPS crypto. | |

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

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-fips-crypto-bom-waivers-1 | Waiver names target and reason | Implemented | Each `fips_waivers` entry names the plugin/artifact + provider being excused and carries a mandatory `reason`; a blank reason is rejected. | You cannot waive silently. |
| req-fips-crypto-bom-waivers-2 | Waived findings stay auditable | Implemented | A waived finding stops failing but is recorded as WAIVED with its reason. | Exception, not erasure. |
| req-fips-crypto-bom-waivers-3 | Operator-only authority | Implemented | Waivers live in the boot profile; a plugin's own manifest cannot waive. | The deployer holds the authority. |

### JVM-Arrival Tripwire
----
RID: `req-fips-crypto-bom-jvm`
Status: `Implemented`

Java/BouncyCastle is out of the current scope (Python + subprocess Go tools + Rust extensions), but its
arrival must not be silent: jars/classes/`libjvm.so` are not ELF, so the fingerprinter is blind to JVM
crypto (JCA providers / BouncyCastle → BC-FIPS). The gate fails-closed the moment a JVM runtime,
executable, `.jar`/`.class` artifact, or bridge distribution (`jpype`/`pyjnius`/`jep`/`py4j`) appears —
the loud "now build the Java crypto layer" signal, rather than shipping a silent non-FIPS JVM.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-fips-crypto-bom-jvm-1 | JVM artifacts fail closed | Implemented | A JVM runtime, executable, or `.jar`/`.class` artifact in the scanned environment fails the gate. | The fingerprinter is ELF-blind to JVM crypto. |
| req-fips-crypto-bom-jvm-2 | Bridge distributions fail closed | Implemented | An installed `jpype`/`pyjnius`/`jep`/`py4j` distribution fails the gate. | The loud build-the-Java-layer signal. |

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

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-fips-crypto-bom-source-1 | Non-validated imports flagged | Implemented | The AST walk flags pure-Python / non-OpenSSL crypto imports; an undispositioned finding fails. OpenSSL-routed modules (`hashlib`, `hmac`, `secrets`, `ssl`, `cryptography`, `psycopg`) are not flagged. | |
| req-fips-crypto-bom-source-2 | Weak-digest security use flagged | Implemented | A bare MD5 construction for a security use (no `usedforsecurity=False`) is flagged at build time; SHA-1 as a hash is approved and not flagged. | Automates the assessment record's F13. |
| req-fips-crypto-bom-source-3 | WASM runtime tripwire | Implemented | An imported or installed WASM host runtime (`wasmtime`/`wasmer`/`pywasm`) fails closed. | The `libjvm.so` pattern for WASM. |

### Pin Currency
----
RID: `req-fips-pin-currency`
Status: `Partial`

`req-cicd-supply-chain-provenance-3` proves the source we compile is the source OpenSSL published.
It says nothing about whether the thing we pinned is still the thing we should pin. Those pins —
`OSSL_VERSION`, `OSSL_SHA256`, `OSSL_SIGNING_PRIMARY` in `docker/build-openssl-fips.sh`, plus the
committed key — are transcribed by a human, reviewed once, and were then not looked at again for
three days.

**The tension this requirement exists inside.** A CMVP-validated module is *frozen at the validated
version, by construction* — certification is of a specific build, so "validated" and "currently
patched" are mutually exclusive properties of the same artifact. FIPS therefore **adds** patch-lag
risk rather than removing it. The goal cannot be to close that gap; it is to **bound it and see it**:
know promptly when the frozen module is affected, and have a pre-decided path to move.

**The operator ruling that governs the move (2026-08-31, read literally on 2026-09-02 — decision
D17 in the assessment record):** *a secure OpenSSL matters more than a FIPS-validated one.* Patching
a serious flaw is the **expected** outcome, not merely a permitted one, and validated-module status is
what yields. "We shipped a known-vulnerable crypto provider because moving would have cost us the
certificate" is not a position this project takes. D17 applies this to the pin itself: it tracks the
FIPS code line's patched releases, the shipped artifact honestly declares "not validated as shipped"
when the version has no certificate (a distinct crypto-BOM state, `req-fips-crypto-bom-1`), and the
per-CVE triage that justified the first move (`docs/misc/doc-fips-provider-cve-triage-2026-09.md`)
is the standing pattern for every later one. The exit ramp in `docker/build-openssl-fips.sh` states
the same rule at the point of use.

#### Detecting when to bump

Four distinct triggers, and they are **not** interchangeable:

| Trigger | Signal | Who sees it |
| --- | --- | --- |
| The release bytes changed | published sha256 no longer matches the pin | `scripts/verify-openssl-release` |
| The signing key was delisted or rotated | pinned primary absent from `doc/fingerprints.txt` **at the tag** | `scripts/verify-openssl-release` |
| A CVE affects the provider | NVD/CPE match on the SBOM component, then triage | `req-cicd-sbom-3` CPE + a scanner (open) |
| The certificate went Historical | CMVP status for #4282 | **nothing today — NOT OBSERVABLE** |

#### Checked and rejected: a FIPS-provider-specific CPE

The obvious way to kill the false-positive rate is a CPE naming the *provider* rather than the
library. One exists and **must not be used**:

```
cpe:2.3:a:openssl:fips_object_module:-:*:*:*:*:*:*:*
```

| | |
| --- | --- |
| Title | "OpenSSL Project FIPS Object Module" |
| Version dimension | `-` — a single entry, no versions |
| Last modified in NVD | **2008-03-25** |
| CVEs matching | **1** — CVE-2007-5502, a PRNG flaw in FIPS Object Module **1.1.1** |

That is the **OpenSSL 1.x-era FIPS Object Module**, a separately distributed product with its own
certificates. Our `fips.so` is the **3.x FIPS provider**, built from the *main* OpenSSL source tree
by `./Configure enable-fips` — which is why NVD indexes it under `cpe:2.3:a:openssl:openssl`, the
same CPE as the library. Upstream, it is the same source release. **There is no 3.x
provider-specific CPE.**

Declaring the object-module CPE would produce a component matching essentially nothing, forever,
while **looking like coverage** — an SBOM entry with a CPE and a scanner reporting clean. That is a
strict downgrade from the noisy-but-honest `openssl:openssl:<version>`, and precisely the
declaration-that-is-false failure this spec exists to prevent.

**Consequence:** the ~37-of-38 noise ratio is not a defect in our declaration, it is inherent to how
NVD models a provider that ships inside a library release. The narrowing therefore has to happen on
our side, and the `strings fips.so` triage in the `bump-openssl-fips` skill **is our substitute for
a CPE that does not exist**. Do not re-litigate this without new upstream data; it was checked
2026-08-31.

⚠️ **A newer version existing is NOT a trigger.** A routine "3.5.x is available" PR against a pin
frozen by validation is noise, and a channel whose alerts are always closed on sight teaches its
reader to miss the one that matters. Detection here must be **vulnerability-triggered, never
version-triggered** — which is why Renovate is deliberately not pointed at this pin.

#### Running the script

```
scripts/verify-openssl-release              # drift check against the current pin
scripts/verify-openssl-release <version>    # bump helper: print that version's pin values
```

Exit codes are three-valued and distinguishable on purpose: `0` all hold, `1` something CHANGED,
`2` something is NOT OBSERVABLE. A caller must not collapse 1 and 2 — "upstream moved" and "we are
blind" demand different responses, and treating the second as success is the absence-as-evidence
failure this whole spec exists to avoid.

The bump procedure itself is the `bump-openssl-fips` skill, which carries the decision gate, the
transcription steps, the multi-file edit set, and the traps. It is authored as a skill rather than a
doc because it is a rare, high-stakes, AI-operable procedure (`specs/spec-ai-integration.md`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-fips-pin-currency-1 | Pins are re-assertable on demand | Implemented | A single command re-checks every pinned fact against upstream: the published sha256, the presence of the detached signature, the signer's authorization **at the release tag**, and that the committed key still exports the pinned primary. | `scripts/verify-openssl-release`. Verified by watching it fail, not only pass: a tampered digest, an unauthorized primary, and an unfetchable version each produce the right state. |
| req-fips-pin-currency-2 | The watcher derives the pins it watches | Implemented | The checker MUST read the pins from `docker/build-openssl-fips.sh`, never restate them. | A watcher carrying its own copy of the value it watches is the failure it exists to prevent. |
| req-fips-pin-currency-3 | Three states, never two | Implemented | Every check reports HOLDS / CHANGED / **NOT OBSERVABLE**, with distinct exit codes. Upstream data whose *shape* is unrecognised reads as NOT OBSERVABLE, never as a value. | Earned: the `.sha256` asset format is not stable across releases (3.0.9 publishes a bare digest, 3.0.16 publishes `<digest>  <filename>`), and the naive parse produced a plausible wrong pin. |
| req-fips-pin-currency-4 | A bump is transcribed, never typed | Implemented | Bump mode prints the target version's pin values from upstream, and prints what remains a human decision (certificate status or a recorded security-driven move, signer change, the SBOM fields). | It MUST NOT edit files or open PRs: moving off a validated module is a re-validation decision, and a bot doing it quietly would be the wrong artifact entirely. |
| req-fips-pin-currency-5 | The check runs without being remembered | Proposed | The drift check runs on a schedule and raises where a human sees it. | Open — tap#231. Until it lands, the pins are only as current as the last time somebody ran the command. |
| req-fips-pin-currency-6 | Certificate status is observable | Proposed | Whether the pinned version's CMVP certificate is still Active is checkable, or is reported NOT OBSERVABLE. | Open as automation. Observed by hand 2026-09-02 from the certificate pages: #4282 (3.0.8/3.0.9, FIPS 140-2) is Active with **sunset 2026-09-21**; #4985 (3.1.2, FIPS 140-3) is Active, sunset 2030-03-10 — both transcribed into `OSSL_CMVP_VALIDATED`. The certificate page is plain HTML and readable; nothing schedules the read. |
| req-fips-pin-currency-7 | Provider-level CVE triage | Implemented | Because no FIPS-provider-specific CPE exists, a CVE matched against the library CPE MUST be triaged against the shipped module before it is acted on — ask the binary (`strings fips.so`), not the description, and OpenSSL's own advisory boundary sentence where it exists. | The `bump-openssl-fips` skill carries the procedure; `docs/misc/doc-fips-provider-cve-triage-2026-09.md` is the worked instance (46 matches: 5 inside, 41 outside, 0 not determinable) and the standing pattern. Without this step the channel is noise and gets ignored. |
| req-fips-pin-currency-8 | Validation claims derive from the pin | Implemented | Whether the shipped provider is CMVP-validated, and under which certificate, is DERIVED from `docker/build-openssl-fips.sh` (`OSSL_VERSION` against the `OSSL_CMVP_VALIDATED` table, via `tap.fips_pins`) by the crypto-BOM, the SBOM's `tap:fips-validation` property, and the README's status clause. A hand-written `CMVP #NNNN` or "FIPS-validated" in those surfaces that disagrees with the derivation fails; an unvalidated version is the distinct FIPS_MODE_UNVALIDATED_BUILD state, never VALIDATED; at boot the classification follows the ACTIVE provider's version and a pin/active mismatch is recorded in the report (not observable → unclassified, refused). | `tap.guards.fips_claims` (per-commit), `scripts/sbom/generate.py` (fail-closed at publish), `tap.crypto_bom.shipped_provider_finding` (boot, FIPS mode). Presence-is-not-correctness applied to the compliance claim itself: D17 makes the claim false the day the pin moves, so the claim must be derived, not written. |

---

## FIPS Requirement Map

The authoritative inventory of every FIPS requirement in the codebase. Requirements **owned here** carry
the full contract above; requirements **homed elsewhere** keep their structural spec (the base-image
build recipe belongs with the base image; the OIDC rescue with auth; the manifest declaration with the
manifest) and are indexed here so the whole FIPS posture reads from one place. Adding a FIPS requirement
anywhere requires adding its row here in the same change.

| Requirement | Home spec | What it covers |
| --- | --- | --- |
| `req-fips-crypto-bom` (+ `-ci`, `-conformance`, `-system-gate`, `-waivers`, `-jvm`) | **this spec** | The crypto Bill-of-Materials: scanner, registry, CI gate, per-plugin conformance, boot-time global gate, operator waivers, JVM tripwire. |
| `req-fips-pin-currency` | **this spec** | Re-asserting the validated module's pins against upstream, the four bump triggers, and the transcribe-don't-type bump path (`scripts/verify-openssl-release` + the `bump-openssl-fips` skill). |
| `req-cicd-base-image-lifecycle-3` | [spec-cicd-hardening.md](spec-cicd-hardening.md) | Wolfi is the standard base — chosen partly for in-image, host-independent FIPS (also for Python-currency + CVE floor). |
| `req-cicd-base-image-lifecycle-5` | [spec-cicd-hardening.md](spec-cicd-hardening.md) | The FIPS crypto recipe: self-built OpenSSL FIPS provider at the pinned version (validation derived, D17) on web + DB, `fipsinstall` in-image, `--no-binary cryptography`, `psycopg[c]` (system libpq), Postgres `--encoding=UTF8 --locale=C`. |
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
