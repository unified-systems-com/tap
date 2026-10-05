"""Minimal reproduction.

cryptography's own EC keygen succeeds cleanly. A plain, separate `_hashlib` fetch for
SHA-256 -- an algorithm the active FIPS provider genuinely implements -- fails
immediately afterward, in the same process, with no refused/negative-control fetch
anywhere in between.

Expected on real x86_64 hardware under this FIPS provider config:
    cryptography EC keygen+sign: OK
    Traceback (most recent call last):
      ...
    _hashlib.UnsupportedDigestmodError: [digital envelope routines] unsupported

Expected on aarch64, or under QEMU emulation of amd64 (does not reproduce):
    cryptography EC keygen+sign: OK
    plain _hashlib sha256 fetch: OK <hexdigest>
"""

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

key = ec.generate_private_key(ec.SECP256R1())
signature = key.sign(b"assertion", ec.ECDSA(hashes.SHA256()))
key.public_key().verify(signature, b"assertion", ec.ECDSA(hashes.SHA256()))
print("cryptography EC keygen+sign+verify: OK")

import _hashlib  # noqa: E402

digest = _hashlib.new("sha256", b"probe")
digest.hexdigest()
module = type(digest).__module__
print("plain _hashlib sha256 fetch: OK, module =", module)
