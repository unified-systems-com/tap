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
  a compiled-in `_md5` on some bases (L5). Every probe in this module, positive or negative,
  uses `_hashlib` directly and never imports `hashlib` itself: the wrapper's own import-time
  bulk-construction of every standard hash name was found to corrupt the process's crypto
  context on a refused MD5 fetch badly enough to take out *later names in the same loop*,
  including the approved SHA-256 this module's own positive control needs (L18).

This module is pure stdlib + `cryptography` (webauthn's engine — the real integration point,
whose wheel would otherwise bundle its own non-FIPS OpenSSL, L9). It imports no `tap_*` app,
so it can run standalone at boot before Django setup, and belongs in `tap/` per CLAUDE.md's
"push shared mechanics down; no tap_* interdependencies" rule.

Run as the boot gate: ``python -m tap.fips`` — exit 0 on a proven-consistent mode, non-zero
(with a ``TAP-ABORT``-friendly message on stderr) otherwise. docker/entrypoint.sh wires it in.
"""

from __future__ import annotations

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
    """Positive control: an approved hash (SHA-256) works AND is OpenSSL-backed.

    Uses ``_hashlib`` directly rather than the ``hashlib`` wrapper module (tap#933/#931, L18):
    merely IMPORTING ``hashlib`` makes CPython eagerly pre-build a constructor for every
    standard hash name in one loop, including MD5. Under FIPS that MD5 build attempt is a
    refused fetch, and the fetch-cache corruption it leaves behind was found to take out
    *later names in that same loop* — including SHA-256 itself (observed:
    ``AttributeError: module 'hashlib' has no attribute 'sha256'``, real CI hardware). A lazy,
    deferred ``import hashlib`` was not sufficient for this reason: the hazard is the import
    itself, not its timing. ``_hashlib`` has no such bulk-construction loop — it is exactly
    the "layer that cannot fall back" L5 already uses for the negative control below, now also
    used for the positive one, so this function never imports ``hashlib`` at all.
    """
    import _hashlib

    digest = _hashlib.new("sha256", b"probe")
    digest.hexdigest()
    module = type(digest).__module__
    if module != "_hashlib":
        raise FipsSelfCheckError(f"SHA-256 is not OpenSSL-backed (module={module!r}); cannot trust the FIPS boundary.")


def _cryptography_positive_control(*, expect_enforced: bool) -> None:
    """Positive control: `cryptography` (webauthn's engine) executes the approved passkey path.

    This is THE integration point (L9): its wheel would statically bundle a private OpenSSL
    that ignores the system FIPS config, so we build it --no-binary and verify here that it
    links the system provider. P-256 ECDSA sign+verify — the exact passkey assertion path.

    Deliberately separate from the MD5 negative control below (tap#933/#931, L18): a function
    that ran its own positive control then its own negative control, back to back, was found to
    poison the shared context for whatever ran NEXT regardless — the negative control's refused
    fetch doesn't care that ITS OWN positive control already succeeded; it still leaves the
    context unable to satisfy the following caller's fetch. Every positive control across this
    whole self-check must run before every negative one, not just within one function.
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

    key = ec.generate_private_key(ec.SECP256R1())
    signature = key.sign(b"assertion", ec.ECDSA(hashes.SHA256()))
    key.public_key().verify(signature, b"assertion", ec.ECDSA(hashes.SHA256()))


def _cryptography_md5_refused() -> None:
    """Negative control (FIPS only): a non-approved digest is refused by `cryptography`.

    Run this LAST, after every positive control this self-check needs (L18) — see
    `_cryptography_positive_control`'s docstring for why.
    """
    from cryptography.hazmat.primitives import hashes

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


def openssl_cores(maps_text: str) -> set[str]:
    """Return the distinct libcrypto files mapped into a process, from its ``/proc/<pid>/maps`` text.

    One path per OpenSSL *core*: every segment of one library shares one path, so two paths
    mean two independent OpenSSL engines in one process.
    """
    cores = set()
    for line in maps_text.splitlines():
        fields = line.split()
        if len(fields) < 6:
            continue
        name = fields[-1].rsplit("/", 1)[-1]
        # The system's `libcrypto.so.3`, and the hashed names a wheel bundles its own copy
        # under (`libcrypto-1a2b3c.so.3`, auditwheel's convention): either is a core.
        if name.startswith(("libcrypto.so", "libcrypto-")) and ".so" in name:
            cores.add(fields[-1])
    return cores


def _assert_single_openssl_core(maps_text: str | None = None) -> None:
    """Refuse to boot if more than one OpenSSL core is loaded (tap#933 root cause).

    Two libcrypto builds in one process both read the FIPS config and both load the one
    ``fips.so``, whose static state a second loader cannot use (openssl/openssl#27691). The
    failure then surfaces much later and far away, e.g. ``rand_new_drbg: unable to fetch
    drbg`` in an unrelated keygen. tap#933 hit it from a uv cache that served a
    ``cryptography`` wheel compiled against OpenSSL 3.6 into an image whose CPython uses 4.0.
    The same collision has other roads: a dependency bundling its own OpenSSL (L17), or libpq
    linked to a different OpenSSL than Python (tap#933's libpq-18). So this checks the
    outcome, not any one cause.

    Every library that does crypto in this process is IMPORTED first, which maps it without
    running any crypto; that has to come before the first positive control, because in the
    two-core case that control is exactly what dies.

    Bounded: this sees cores that are mapped as their own file. An OpenSSL linked *statically*
    into an extension maps as that extension (`_rust.abi3.so`) and is invisible here. TAP builds
    `cryptography` and `psycopg` from source against the system OpenSSL (D7/L9), and a
    `cryptography` carrying its own non-FIPS copy would compute MD5, which
    `_cryptography_md5_refused` refuses; any other native crypto is the crypto-BOM gate's
    (`tap.crypto_bom`, ELF fingerprints), which runs right after this self-check.
    """
    if maps_text is None:
        import _hashlib  # noqa: F401 - CPython's OpenSSL binding.

        for module in ("cryptography.hazmat.bindings._rust", "psycopg"):
            try:
                __import__(module)
            except ImportError:
                continue  # absent here; the positive controls below report what matters.
        try:
            with open("/proc/self/maps", encoding="utf-8") as handle:
                maps_text = handle.read()
        except OSError as exc:
            # Fail closed: this runs only under a FIPS declaration, and an unreadable maps file
            # would turn the check into a pass. The image always has /proc; tests pass the text in.
            raise FipsSelfCheckError(
                f"cannot read /proc/self/maps ({exc}), so a second OpenSSL core cannot be ruled out."
            ) from exc
    cores = openssl_cores(maps_text)
    if len(cores) > 1:
        raise FipsSelfCheckError(
            f"{len(cores)} OpenSSL libraries are loaded in one process ({', '.join(sorted(cores))}); "
            "under FIPS they share one fips.so and break each other. A package was built against "
            "a different OpenSSL than this image's Python: a stale uv cache or venv volume from an "
            "older image, or a wheel bundling its own OpenSSL. Clear the venv and uv_cache "
            "volumes and reboot."
        )


def assert_declared_mode() -> str:
    """Prove the declared FIPS mode is the mode actually enforced, or raise.

    Returns the declared mode string on success (for the caller to report).
    """
    mode = declared_mode()
    if mode == "1":
        # Before any crypto runs: in the two-core case the first positive control is what dies,
        # with an error that points nowhere near the cause.
        _assert_single_openssl_core()
        # ALL positive controls run first, THEN all negative ones (tap#933/#931, L18): a
        # correctly-refused MD5 fetch in the process's default OSSL_LIB_CTX leaves that context
        # unable to satisfy a LATER, unrelated fetch from anything — CTR-DRBG, SHA-256, any of
        # it — for the rest of the process's life. Proven on real CI hardware to be 100%
        # reproducible with any MD5 touch (via `_hashlib`, `hashlib`'s own import-time behavior,
        # or `cryptography`'s own negative control) before a later positive operation, and 100%
        # absent when every positive runs first. `_cryptography_positive_control` and
        # `_cryptography_md5_refused` are deliberately separate functions, not one function run
        # twice, so this ordering is enforced across the whole self-check, not just within it.
        _cryptography_positive_control(expect_enforced=True)
        _approved_python_hash_works()
        if not _md5_for_security_refused():
            raise FipsSelfCheckError(
                "image declares FIPS on (TAP_FIPS_MODE=1) but _hashlib MD5 for security use was "
                "NOT refused — the OpenSSL FIPS provider config did not take effect (the L1 "
                "fail-open trap). Refusing to serve."
            )
        _cryptography_md5_refused()
    else:
        # Non-FIPS declared: prove it does NOT enforce, so the image cannot silently lie about
        # its posture in the other direction. A refusal here means the image claims non-FIPS
        # while FIPS is actually active — a declaration mismatch, also fail-closed. No ordering
        # hazard in this branch: MD5 is expected to SUCCEED (not be refused) when FIPS is off,
        # so there is no refused fetch here to poison anything.
        if _md5_for_security_refused():
            raise FipsSelfCheckError(
                "image declares FIPS off (TAP_FIPS_MODE=0) but MD5 for security use is refused — "
                "the running crypto posture does not match the declared mode."
            )
        _cryptography_positive_control(expect_enforced=False)
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
