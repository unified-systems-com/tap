"""The curated crypto-provider registry — the reviewable decision surface of the crypto-BOM gate.

The FIPS invariant is NOT "everything uses OpenSSL." It is: **every cryptographic *provider* that
can execute inside the deployed artifact is the validated module (the system OpenSSL provider at the
pinned version — validated, or a recorded unvalidated build, per `tap.fips_pins`), or that
ecosystem's validated equivalent — or is proven unreached, or explicitly named out-of-boundary.**
OpenSSL is merely the provider TAP's *Python* uses; a Go binary, a Rust crate on `ring`/`aws-lc-rs`,
a `libsodium`/`pynacl` wheel, or a JVM's BouncyCastle each carries its OWN crypto that is invisible to
`OPENSSL_CONF` and would silently run non-FIPS crypto with no error (doc-fips-assessment-record.md L17).

`tap.crypto_bom` scans an environment (core's venv + image binaries, or a single plugin's closure —
because plugins run in the same process/image and it does us no good to make core FIPS-capable if a
plugin leaks) and fingerprints the crypto providers actually present. This module is the *data* it
checks against: (1) the byte SIGNATURES that detect each provider, and (2) the DISPOSITIONS that say,
for each provider found, whether it is acceptable and why. Adding a disposition is the reviewable act —
exactly like `tap.guards.surfaces.DECLARED_SURFACES`. A provider detected with NO disposition fails the
gate (fail-closed): a new dependency or binary carrying an unclassified crypto provider cannot ship
until a human classifies it.

Scope (decided 2026-07-21): Python + subprocess Go tools + Rust extensions. JVM/BouncyCastle is out of
scope until a plugin actually brings a JVM; its signatures are listed so the gate *detects* one and
fails-closed rather than missing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: The requirement this gate realizes (spec-cicd-hardening.md).
CRYPTO_BOM_RID = "req-fips-crypto-bom"


class Boundary(StrEnum):
    """A provider's disposition relative to the FIPS cryptographic boundary."""

    #: Routes through the validated module (the system OpenSSL provider at a CMVP-validated
    #: version, per `tap.fips_pins`) or an ecosystem-validated one.
    VALIDATED = "validated"
    #: Routes through the system OpenSSL provider while the PINNED version carries no CMVP
    #: certificate: FIPS mode on, approved-algorithms-only, built from OpenSSL's FIPS code line —
    #: a recorded security-driven build (decision D17). Not a failure, and not VALIDATED: the
    #: distinct state exists so presence can never be read as a certificate.
    FIPS_MODE_UNVALIDATED_BUILD = "fips-mode-unvalidated-build"
    #: Provisioning / supply-chain crypto (package fetch + hash verify), named-accepted as outside
    #: the *operational* boundary — like apk's own signature checks. Disclosed, not hidden.
    OUT_OF_BOUNDARY = "out-of-boundary"
    #: Present in the artifact but never executes a security operation (e.g. a Go binary linked with
    #: crypto/tls from the stdlib that only ever setuids). Must carry a reachability argument.
    UNREACHED = "unreached"
    #: Non-validated crypto inside the operational boundary — the gate FAILS on this. It is recorded
    #: (not merely absent) so a known-bad provider is tracked with its remediation, not silently green.
    MUST_FIX = "must-fix"


@dataclass(frozen=True)
class Signature:
    """A byte-signature that detects a crypto provider in a native (ELF) artifact.

    ALL needles must be present for a match (AND semantics) — this is how `go-crypto` is
    disambiguated from a stray `crypto/tls` string in a non-Go binary (it also requires the Go
    build-info magic). Multiple Signatures may map to the same `provider` (OR at the provider level).
    """

    provider: str
    needles: tuple[bytes, ...]
    #: "validated-openssl" (routes through system OpenSSL), "embedded-openssl" (a bundled/static
    #: OpenSSL banner — suspicious unless it IS the system libcrypto), or "non-openssl".
    kind: str
    note: str


# Ordered detection signatures. Byte-searched in each ELF artifact.
SIGNATURES: tuple[Signature, ...] = (
    # --- routes through the SYSTEM OpenSSL (the pinned FIPS provider) ------------------------------
    # A DT_NEEDED reference to the system libcrypto, directly or transitively via a system library
    # that itself dynamically links the one system libcrypto (there is exactly one on the image):
    # libssl (TLS), libpq (psycopg[c] → L17), libcurl (git's HTTPS). Any of these = validated.
    # (The bundled-OpenSSL class is caught reliably by the separate-libcrypto-FILE check in
    # crypto_bom, and a statically-bundled cryptography wheel is caught by the tap.fips boot
    # self-check — so an embedded OpenSSL *version banner* is deliberately NOT used as a signal: it
    # is build metadata, e.g. `git` embeds the system "OpenSSL 3.6.3" string it was built against.)
    Signature("openssl-system", (b"libcrypto.so.3",), "validated-openssl", "links system libcrypto"),
    Signature("openssl-system", (b"libssl.so.3",), "validated-openssl", "links system libssl → system libcrypto"),
    Signature("openssl-system", (b"libpq.so.5",), "validated-openssl", "links system libpq → system libcrypto"),
    Signature("openssl-system", (b"libcurl.so.4",), "validated-openssl", "links system libcurl → system libcrypto"),
    # --- non-OpenSSL providers (each MUST be dispositioned; invisible to OPENSSL_CONF) -------------
    Signature(
        "go-crypto",
        (b"Go buildinf:", b"crypto/tls"),
        "non-openssl",
        "Go stdlib crypto (needs GODEBUG=fips140/boringcrypto)",
    ),
    Signature("rust-ring", (b"ring_core_",), "non-openssl", "Rust `ring` (BoringSSL-derived; not FIPS)"),
    Signature(
        "rust-aws-lc-rs",
        (b"aws_lc_",),
        "non-openssl",
        "Rust aws-lc-rs (aws-lc IS CMVP-validatable via its FIPS feature)",
    ),
    Signature("libsodium", (b"sodium_init",), "non-openssl", "libsodium / PyNaCl (not FIPS)"),
    Signature("mbedtls", (b"mbedtls_ssl_init",), "non-openssl", "mbed TLS (separate validation)"),
    Signature("wolfssl", (b"wolfSSL_Init",), "non-openssl", "wolfSSL (separate validation)"),
    Signature("gnutls", (b"gnutls_global_init",), "non-openssl", "GnuTLS (not our validated module)"),
    Signature("nss", (b"NSS_Initialize",), "non-openssl", "Mozilla NSS (separate validation)"),
    Signature("boringssl", (b"BoringSSL",), "non-openssl", "BoringSSL (not our validated module)"),
    # JVM/BouncyCastle: out of scope, but detected so the gate fails-closed if a plugin brings a JVM.
    Signature(
        "bouncycastle", (b"org/bouncycastle/",), "non-openssl", "BouncyCastle — use BC-FIPS (out of current scope)"
    ),
)


@dataclass(frozen=True)
class Disposition:
    """A reviewed decision: this provider, on artifacts matching this glob, is acceptable because…

    `artifact` is an fnmatch glob over the artifact's absolute path (native binaries) or the
    distribution name (Python-name findings). `provider` is the detected provider, or "*" for any.
    """

    artifact: str
    provider: str
    boundary: Boundary | None
    rationale: str
    rid: str


@dataclass(frozen=True)
class Waiver:
    """An OPERATOR (deployment-side) decision to accept a specific non-validated crypto provider in a
    FIPS-mode system, WITH a mandatory justification.

    Authority — the load-bearing design decision: a plugin AUTHOR cannot waive a system security
    property. Letting a plugin mark *itself* FIPS-exempt would let a careless or hostile plugin
    silently opt out of the deployment's FIPS posture — the exact leak the crypto-BOM closes. So a
    waiver is DEPLOYMENT-scoped: it lives in the boot profile's `fips_waivers` (operator-controlled),
    names the plugin/artifact + provider being excused, and REQUIRES a `reason`. Every FIPS exception
    is therefore explicit and auditable, never silent (spec-security-posture: name the risks left open).
    The plugin author's role is only to *declare* posture (factual), which the conformance scan verifies.
    """

    #: fnmatch glob over a finding's artifact (an absolute path, or `dist:<name>`, or a plugin slug).
    artifact: str
    #: The provider being excused, or "*" for any provider on the matched artifact.
    provider: str
    #: Mandatory human justification — an empty reason is rejected at load (you cannot waive silently).
    reason: str


def system_openssl_boundary() -> tuple[Boundary | None, str]:
    """The disposition of everything that routes through the system OpenSSL, DERIVED from the pin.

    VALIDATED when the pinned provider version carries a CMVP certificate; the distinct
    FIPS_MODE_UNVALIDATED_BUILD when it does not (D17); and None — unclassified, so the gate fails
    closed — when the pins cannot be read at all. A certificate is never assumed from presence.
    """
    from tap.fips_pins import PinsUnreadable, read_pins

    try:
        pins = read_pins()
    except PinsUnreadable as exc:
        return None, f"FIPS provider pins NOT OBSERVABLE ({exc}) — cannot classify OpenSSL-routed crypto"
    if pins.validation:
        return Boundary.VALIDATED, (
            f"Routes through the system OpenSSL — the validated provider ({pins.status_clause()}; "
            "tap.fips proves it is enforced at boot). Directly, or transitively via the system libpq."
        )
    return Boundary.FIPS_MODE_UNVALIDATED_BUILD, (
        f"Routes through the system OpenSSL in FIPS mode — {pins.status_clause()}. "
        "Approved-algorithms-only is enforced (tap.fips), the certificate is not claimed."
    )


SYSTEM_OPENSSL_BOUNDARY, SYSTEM_OPENSSL_RATIONALE = system_openssl_boundary()

# The dispositions. A finding with no matching disposition is UNKNOWN → the gate fails (fail-closed).
DISPOSITIONS: tuple[Disposition, ...] = (
    # Any artifact that routes through the system OpenSSL / system libpq takes the DERIVED system
    # boundary (validated or the unvalidated-build state, per the pin), proven enforced by tap.fips.
    Disposition(
        "*",
        "openssl-system",
        SYSTEM_OPENSSL_BOUNDARY,
        SYSTEM_OPENSSL_RATIONALE,
        CRYPTO_BOM_RID,
    ),
    # Python distributions whose crypto is the system OpenSSL (dispositioned by name, since the link is
    # via the build config / an indirect libpq chain rather than always a direct DT_NEEDED).
    Disposition(
        "cryptography",
        "*",
        SYSTEM_OPENSSL_BOUNDARY,
        "Built --no-binary against the system OpenSSL (D7/L9); its _rust.abi3.so links "
        "libcrypto.so.3, verified by the tap.fips cryptography self-check.",
        CRYPTO_BOM_RID,
    ),
    Disposition(
        "psycopg-c",
        "*",
        SYSTEM_OPENSSL_BOUNDARY,
        "psycopg[c] links the system libpq → system OpenSSL (L17 — replaced psycopg[binary]'s "
        "bundled OpenSSL, which broke SCRAM under FIPS).",
        CRYPTO_BOM_RID,
    ),
    Disposition(
        "psycopg",
        "*",
        SYSTEM_OPENSSL_BOUNDARY,
        "The psycopg meta-package; the installed C implementation is psycopg-c (system libpq).",
        CRYPTO_BOM_RID,
    ),
    # uv: a provisioning tool. Its rustls + aws-lc-rs do TLS to the package index and SHA-256 hash
    # verification at INSTALL time — supply-chain integrity, not operational crypto in the request path.
    Disposition(
        "*/uv",
        "rust-aws-lc-rs",
        Boundary.OUT_OF_BOUNDARY,
        "uv is a provisioning tool: its aws-lc-rs TLS + package-hash verification run at install "
        "time, not in the operational request path — supply-chain integrity, like apk's own "
        "signature checks. aws-lc IS CMVP-validated, so enabling uv's FIPS build is the "
        "escalation if provisioning is ever ruled in-boundary.",
        CRYPTO_BOM_RID,
    ),
    Disposition(
        "*/uvx", "rust-aws-lc-rs", Boundary.OUT_OF_BOUNDARY, "uvx ships with uv; same rationale.", CRYPTO_BOM_RID
    ),
    # gosu (db image): drops privileges root→postgres and execs; the Go crypto/tls linked from the
    # stdlib is never invoked — it does no TLS. Present-but-unreached.
    Disposition(
        "*/gosu",
        "go-crypto",
        Boundary.UNREACHED,
        "gosu setuids from root to the postgres user and execs postgres; the Go stdlib's "
        "crypto/tls is linked but never called — gosu opens no TLS connection.",
        CRYPTO_BOM_RID,
    ),
)


#: Python distributions known to carry NON-system-OpenSSL crypto (bundled native or pure-Python), so
#: the name check flags them even when byte-fingerprinting cannot reach them (pure-Python has no .so;
#: some link indirectly). Each, if ever installed, must earn a Disposition or be removed. This is the
#: belt to the fingerprinter's braces for the crypto TAP does not currently pull.
KNOWN_NONFIPS_DISTRIBUTIONS: frozenset[str] = frozenset(
    {
        "pynacl",  # libsodium
        "bcrypt",  # its own blowfish impl
        "pycryptodome",  # its own primitives
        "pycryptodomex",
        "ed25519",  # pure-python / ref10
        "nacl",
        "cryptg",
        # Pure-Python crypto that the ELF fingerprinter cannot see — no native extension to scan
        # (req-fips-crypto-bom-source). Caught here by installed-DIST name (direct or transitive).
        "ecdsa",  # pure-Python ECDSA (python-jose's default backend)
        "rsa",  # pure-Python RSA
        "python-jose",  # may use the pure-Python ecdsa/rsa backends
        "passlib",  # pure-Python password-hashing schemes
        "argon2-cffi",  # Argon2 — not a FIPS-approved algorithm
        "blake3",  # BLAKE3 — not FIPS-approved
    }
)


# --- Source-level crypto detection (req-fips-crypto-bom-source) --------------------------------------
# The ELF fingerprinter sees NATIVE crypto; the dist-name check sees KNOWN installed packages. Neither
# sees crypto that is PURE-PYTHON and vendored/renamed, nor a weak primitive USED in our own source.
# These drive the AST source scan (tap.crypto_bom.scan_source): the Python analog of the ELF signatures.

#: Top-level import module names that mean NON-VALIDATED crypto MAY execute. `hashlib`/`hmac`/`secrets`/
#: `ssl`/`cryptography`/`psycopg` are deliberately absent — they route through the system OpenSSL
#: (the pinned FIPS provider) or are stdlib-OpenSSL-backed, so importing them is fine. Importing one of these is a finding
#: that must be dispositioned or removed. (Same fail-open-on-a-novel-NAME residual as the ELF signatures.)
NONVALIDATED_CRYPTO_IMPORTS: dict[str, str] = {
    "ecdsa": "pure-Python ECDSA — not the validated module",
    "rsa": "pure-Python RSA — not the validated module",
    "nacl": "PyNaCl / libsodium — not FIPS",
    "Crypto": "pycryptodome — its own primitives, not FIPS",
    "Cryptodome": "pycryptodomex — its own primitives, not FIPS",
    "jose": "python-jose — may use pure-Python ecdsa/rsa backends, not FIPS",
    "passlib": "passlib — pure-Python password schemes, not FIPS",
    "bcrypt": "bcrypt — its own blowfish, not FIPS",
    "argon2": "argon2 — not a FIPS-approved algorithm",
    "blake3": "blake3 — not FIPS-approved",
    "nacl.signing": "PyNaCl signing — not FIPS",
}

#: A bare non-approved digest used for SECURITY (default `usedforsecurity=True`) is a latent runtime
#: bomb under FIPS — it raises only when the path executes. The source scan flags it at build time
#: (automating the assessment record's F13). MD5 is the one that hard-fails; SHA-1 is FIPS-approved as
#: a hash, so it is NOT flagged. `usedforsecurity=False` (the auditor-recognized non-security signal)
#: is exempt.
WEAK_DIGEST_CALLS: frozenset[str] = frozenset({"md5"})

# --- WASM-runtime tripwire (req-fips-crypto-bom-source) ---------------------------------------------
# WebAssembly crypto cannot execute without a host runtime, and in Python that runtime is a package —
# which is native + named, so the runtime is the tripwire (like the JVM's libjvm.so), not the opaque
# `.wasm` module. Detecting the runtime forces the "we don't yet reason about WASM crypto" review.
WASM_RUNTIME_IMPORTS: frozenset[str] = frozenset({"wasmtime", "wasmer", "wasmer_compiler_cranelift", "pywasm", "wasm3"})
KNOWN_WASM_DISTRIBUTIONS: frozenset[str] = frozenset(
    {"wasmtime", "wasmer", "wasmer-compiler-cranelift", "pywasm", "wasm3"}
)


# --- JVM-arrival tripwire ---------------------------------------------------------------------------
# Java is deliberately OUT of the current scope, but its ARRIVAL must not be silent: Java crypto does
# NOT go through OpenSSL — it uses JCA providers (SunJCE, and BouncyCastle, which for FIPS must be
# BC-FIPS), entirely invisible to the ELF fingerprinter (jars/classes are not ELF). So the moment a
# JVM appears in the image or a plugin's closure, the gate fails-closed with a "now build the Java
# crypto layer" finding, rather than shipping a JVM that silently does non-FIPS crypto. These are the
# arrival signals (req-fips-crypto-bom residual (a)).
JVM_RUNTIME_FILES: frozenset[str] = frozenset({"libjvm.so"})
JVM_EXECUTABLES: frozenset[str] = frozenset({"java", "javac", "jar", "jarsigner", "jshell", "keytool"})
JVM_ARTIFACT_SUFFIXES: tuple[str, ...] = (".jar", ".class")
#: Python distributions that embed or bridge to a JVM (they pull/spawn one), catching Java's arrival
#: at the dependency layer even before a JVM binary is on disk.
KNOWN_JVM_DISTRIBUTIONS: frozenset[str] = frozenset({"jpype1", "jpype", "pyjnius", "jep", "py4j", "jaydebeapi"})
