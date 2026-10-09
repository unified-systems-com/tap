"""The FIPS module is installed pedantic (req-fips-pedantic-install, decision D18).

From the 3.5 line on, the module enforces the per-check switches `fipsinstall` writes, and a
plain `fipsinstall` writes them all off: on the 3.5.8 spike, SHA-1 signatures the 3.0.22 module
refused were ALLOWED until `-pedantic` was added. These tests pin the flag in both images and
prove the effect where it matters, in a process running in FIPS mode.

The signing probe runs in a fresh subprocess on purpose. A correctly refused fetch leaves the
process's default library context unable to serve later, unrelated fetches (L18, see tap/fips.py),
so an in-process negative test could "pass" because the context was already poisoned, not
because SHA-1 was refused. The probe's positive control (a SHA-256 signature with the same key)
runs first, and an inconclusive probe fails the test rather than passing it.

Why RSA and not ECDSA: through `cryptography`, an ECDSA SHA-1 signature succeeds even on the
3.0.22 module that refuses SHA-1 signing. Observed while writing this test, and on the 3.5.8
spike even under -pedantic. The likely reason is that `cryptography` hashes first and hands the
module a precomputed digest, so the module never sees the SHA-1 choice; that is an inference.
An ECDSA probe would therefore fail on every module and prove nothing. The RSA PKCS#1 path does
reach the module's digest check: refused on 3.0.22, allowed on 3.5.8 without -pedantic, and
refused with it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = (REPO_ROOT / "Dockerfile", REPO_ROOT / "docker" / "postgres" / "Dockerfile")

# Exit codes: 0 = refused (as required), 1 = SHA-1 signing ALLOWED, 3 = positive control failed.
PROBE = """
import sys
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
try:
    rsa_key.sign(b"x", padding.PKCS1v15(), hashes.SHA256())
except Exception as exc:
    print(f"positive control failed: {exc!r}")
    sys.exit(3)
allowed = []
for name, sign in (
    ("rsa2048-pkcs1-sha1", lambda: rsa_key.sign(b"x", padding.PKCS1v15(), hashes.SHA1())),
):
    try:
        sign()
        allowed.append(name)
    except Exception:
        pass
print("allowed: " + ",".join(allowed))
sys.exit(1 if allowed else 0)
"""


@pytest.mark.spec("req-fips-pedantic-install-1")
@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_fipsinstall_is_pedantic(dockerfile: Path) -> None:
    lines = [
        line.strip()
        for line in dockerfile.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("RUN") and "fipsinstall" in line
    ]
    assert lines, f"no fipsinstall step found in {dockerfile} (the scan would pass vacuously)"
    for line in lines:
        assert " -pedantic " in f"{line} ", f"{dockerfile}: {line}"


@pytest.mark.spec("req-fips-pedantic-install-2")
@pytest.mark.skipif(os.environ.get("TAP_FIPS_MODE") != "1", reason="the image declares FIPS off")
def test_sha1_signing_is_refused_in_fips_mode() -> None:
    result = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — a fresh interpreter IS the test (L18); argv list, no shell, a literal probe  # nosec B603  # noqa: S603
        [sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=120
    )
    assert result.returncode != 3, f"inconclusive — positive control failed: {result.stdout}{result.stderr}"
    assert result.returncode == 0, f"SHA-1 signing was allowed in FIPS mode: {result.stdout}{result.stderr}"
