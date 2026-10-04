"""Fail-closed FIPS-mode boot self-check (req-cicd-base-image-lifecycle-6, decision D15).

The image *declares* its FIPS posture machine-legibly (the `org.tap.fips` OCI label and the
`TAP_FIPS_MODE` environment variable). A declaration is not enforcement: the spike's very
first pass shipped an `openssl.cnf` that "parsed cleanly" yet activated **nothing** and
silently ran the default provider (doc-fips-assessment-record.md L1 — a fail-*open* trap).

So at boot we *prove* the declared mode is the mode actually in effect, and refuse to serve
otherwise. Two disciplines from the assessment record govern how:

* **Execute crypto and observe a refusal — never inspect files.** In OpenSSL 3 the `default`
  and `base` providers are compiled into libcrypto, not shipped as files, so an empty
  `ossl-modules/` proves nothing and the FIPS boundary is the *config*, not the modules
  directory (L13). The only trustworthy evidence is behavioral: a non-approved primitive is
  actually refused.
* **Every positive check is paired with a negative control.** "sha256 works" evidences
  nothing about enforcement; "md5 (for security use) is *refused*" does. Probe the lowest
  layer that cannot fall back — `_hashlib`, not the `hashlib` façade, which can fall back to
  a compiled-in `_md5` on some bases (L5).

This module is pure stdlib + `cryptography` (webauthn's engine — the real integration point,
whose wheel would otherwise bundle its own non-FIPS OpenSSL, L9). It imports no `tap_*` app,
so it can run standalone at boot before Django setup, and belongs in `tap/` per CLAUDE.md's
"push shared mechanics down; no tap_* interdependencies" rule.

Run as the boot gate: ``python -m tap.fips`` — exit 0 on a proven-consistent mode, non-zero
(with a ``TAP-ABORT``-friendly message on stderr) otherwise. docker/entrypoint.sh wires it in.
"""

from __future__ import annotations

import hashlib
import os
import sys

#: The env var the image bakes to declare its mode ("1" = FIPS on, "0" = off).
MODE_ENV = "TAP_FIPS_MODE"


class FipsSelfCheckError(RuntimeError):
    """The image's declared FIPS mode is not the mode actually enforced.

    Raised on any mismatch in either direction — a FIPS-declared image that does not refuse a
    non-approved primitive (the dangerous fail-open case), or a non-FIPS-declared image that
    unexpectedly enforces (the image lies about its posture). Both are fail-closed at boot.
    """


def declared_mode() -> str:
    """Return the declared mode: ``"1"`` (FIPS) or ``"0"`` (non-FIPS).

    An unset/blank declaration is read as ``"0"``: an image that claims nothing is not a
    FIPS image, and we must never *infer* FIPS from silence. The shipped Dockerfile always
    sets this env in both variants; the default only matters for a transitional image built
    before the flag existed.
    """
    raw = os.environ.get(MODE_ENV, "0").strip()
    return "1" if raw == "1" else "0"


def _md5_for_security_refused() -> bool:
    """Execute MD5 for a *security* use at the layer that cannot fall back, and report
    whether it was refused.

    Uses ``_hashlib`` (the OpenSSL-backed module) directly rather than ``hashlib.md5`` so the
    call hits OpenSSL and cannot be masked by a compiled-in ``_md5`` builtin (L5). Default
    ``usedforsecurity=True`` — the non-approved-for-security path FIPS must block. (MD5 with
    ``usedforsecurity=False`` is *permitted* by FIPS for non-security use via a separate
    libctx, L8, so it is deliberately NOT the probe.)
    """
    import _hashlib  # OpenSSL-backed; the layer with no builtin fallback on Wolfi CPython.

    try:
        _hashlib.new("md5", b"probe")
    except ValueError:
        return True  # refused — FIPS enforced at the Python/OpenSSL boundary.
    return False


def _approved_python_hash_works() -> None:
    """Positive control: an approved hash (SHA-256) works AND is OpenSSL-backed."""
    hashlib.sha256(b"probe").hexdigest()
    module = type(hashlib.sha256()).__module__
    if module != "_hashlib":
        raise FipsSelfCheckError(f"SHA-256 is not OpenSSL-backed (module={module!r}); cannot trust the FIPS boundary.")


def _cryptography_fips_consistent(*, expect_enforced: bool) -> None:
    """Assert `cryptography` (webauthn's engine) agrees with the declared mode.

    This is THE integration point (L9): its wheel would statically bundle a private OpenSSL
    that ignores the system FIPS config, so we build it --no-binary and verify here that it
    links the system provider. Positive control: P-256 ECDSA sign+verify — the exact passkey
    assertion path. Negative control (FIPS only): MD5 via `cryptography` is refused.
    """
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as exc:  # pragma: no cover - cryptography is always present post-sync.
        if expect_enforced:
            raise FipsSelfCheckError(
                "cryptography is not importable, so the FIPS integration point cannot be proven."
            ) from exc
        return

    # Positive control (both modes): the approved passkey path executes.
    key = ec.generate_private_key(ec.SECP256R1())
    signature = key.sign(b"assertion", ec.ECDSA(hashes.SHA256()))
    key.public_key().verify(signature, b"assertion", ec.ECDSA(hashes.SHA256()))

    if not expect_enforced:
        return

    # Negative control (FIPS only): a non-approved digest is refused by the same engine.
    try:
        digest = hashes.Hash(hashes.MD5())
        digest.update(b"probe")
        digest.finalize()
    except Exception:  # noqa: BLE001 - cryptography raises InternalError; any refusal is the pass.
        return
    raise FipsSelfCheckError(
        "cryptography computed MD5 under a FIPS-declared image — the system FIPS provider is "
        "NOT in effect for cryptography (is the wheel bundling its own OpenSSL? see D7/L9)."
    )


def assert_declared_mode() -> str:
    """Prove the declared FIPS mode is the mode actually enforced, or raise.

    Returns the declared mode string on success (for the caller to report).
    """
    mode = declared_mode()
    if mode == "1":
        _approved_python_hash_works()
        # cryptography's own positive-then-negative check runs BEFORE the raw _hashlib MD5
        # probe below, not after (tap#933/#931, L18): a correctly-refused MD5 fetch in the
        # process's default OSSL_LIB_CTX leaves that context unable to satisfy a later,
        # unrelated DRBG fetch — proven on real CI hardware to be 100% reproducible with the
        # probe-then-keygen order and 100% absent with keygen-then-probe, independent of
        # architecture, -m invocation, or any tap-specific code (a 5-line reproduction).
        # Every required positive operation must complete before any negative-control probe
        # that can leave the shared context in a refused state.
        _cryptography_fips_consistent(expect_enforced=True)
        if not _md5_for_security_refused():
            raise FipsSelfCheckError(
                "image declares FIPS on (TAP_FIPS_MODE=1) but _hashlib MD5 for security use was "
                "NOT refused — the OpenSSL FIPS provider config did not take effect (the L1 "
                "fail-open trap). Refusing to serve."
            )
    else:
        # Non-FIPS declared: prove it does NOT enforce, so the image cannot silently lie about
        # its posture in the other direction. A refusal here means the image claims non-FIPS
        # while FIPS is actually active — a declaration mismatch, also fail-closed.
        if _md5_for_security_refused():
            raise FipsSelfCheckError(
                "image declares FIPS off (TAP_FIPS_MODE=0) but MD5 for security use is refused — "
                "the running crypto posture does not match the declared mode."
            )
        _cryptography_fips_consistent(expect_enforced=False)
    return mode


def main() -> int:
    """Boot-gate entrypoint: prove the mode, print a one-line result, exit 0/non-zero."""
    try:
        mode = assert_declared_mode()
    except FipsSelfCheckError as exc:
        # Mirror the reserved abort signal the entrypoint watches for (req-boot-abort-signal).
        print(f"TAP-ABORT: fips: {exc}", file=sys.stderr)
        return 1
    label = "ENFORCED (fips provider active; non-approved primitive refused)" if mode == "1" else "off"
    print(f"==> FIPS self-check OK: declared mode {mode} is consistent — {label}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
