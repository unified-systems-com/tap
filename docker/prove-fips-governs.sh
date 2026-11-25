#!/bin/sh
# Prove that `default_properties = fips=yes` governs every ordinary request (decision D21,
# req-fips-optout-inventory-3). Both images load OpenSSL's `default` provider beside `fips` and
# `base`; presence of the providers proves nothing about which one answers. So, through whichever
# config this process reads (the edited system openssl.cnf, or OPENSSL_CONF for the rollback
# activation):
#   - a plain MD5 and a plain ChaCha20 request must be REFUSED;
#   - the same requests with an explicit non-security opt-out (`-propquery -fips`) must SUCCEED.
# The successes are the positive controls: they prove each command line itself works, so a
# refusal above is a refusal, not a typo or a missing tool. Fails the build (exit 1) otherwise.
#
# The MD5 invocations hash the constant "x" as probes, one refused and one served, so the
# weak-hash warning they draw (Sonar S4790) is suppressed on each line.
set -eu

# A fixed all-zero 256-bit key and 128-bit IV, written out: no `seq`/`printf` construction that a
# missing tool could silently turn into a failing command line.
KEY=0000000000000000000000000000000000000000000000000000000000000000
IV=00000000000000000000000000000000

fatal() { echo "FATAL: $*" >&2; exit 1; }
md5()      { printf x | openssl dgst -md5 "$@" >/dev/null 2>&1; }  # NOSONAR (S4790) — a probe, see above
chacha20() { printf x | openssl enc -chacha20 -K "$KEY" -iv "$IV" "$@" >/dev/null 2>&1; }

echo "=== functional check: an ordinary request is served by the FIPS module only ==="
md5 -propquery '-fips' || fatal "an explicit non-security MD5 request (-propquery -fips) failed -- usedforsecurity=False callers (Django's names_digest) would crash"
chacha20 -propquery '-fips' || fatal "the ChaCha20 positive control (-propquery -fips) failed -- the refusal probe below would prove nothing"
if md5; then fatal "a plain MD5 request succeeded -- fips=yes is not governing every fetch"; fi
if chacha20; then fatal "a plain ChaCha20 request succeeded -- a non-approved cipher is reachable without opting out"; fi
echo "ok: plain MD5 and ChaCha20 refused; both served only on an explicit non-security opt-out"
